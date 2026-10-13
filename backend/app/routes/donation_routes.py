"""Donor-facing donation endpoints."""
from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import config
from ..auth import get_current_user, require_roles
from ..database import get_db, utcnow
from ..models import DONATION_STATUSES, Donation, MatchRecommendation, User
from ..notifications import audit
from ..schemas import DonationCreate, DonationOut, DonationUpdate, Page
from ..serializers import donation_out
from ..services import cancel_donation, generate_matches
from . import paginate

router = APIRouter(prefix="/api/donations", tags=["donations"])

_IMAGE_SIGNATURES = {
    b"\xff\xd8\xff": "jpg",
    b"\x89PNG\r\n\x1a\n": "png",
}


def _image_ext(head: bytes) -> Optional[str]:
    for sig, ext in _IMAGE_SIGNATURES.items():
        if head.startswith(sig):
            return ext
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    return None


def get_visible_donation(db: Session, donation_id: int, user: User) -> Donation:
    """Load a donation if the user is allowed to see it (404 otherwise, to avoid leaking ids)."""
    d = db.get(Donation, donation_id)
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Donation not found")
    if user.role == "admin" or d.donor_id == user.id:
        return d
    if user.role == "ngo" and user.ngo_profile:
        nid = user.ngo_profile.id
        if d.ngo_id == nid or db.scalar(select(MatchRecommendation.id).where(
                MatchRecommendation.donation_id == d.id, MatchRecommendation.ngo_id == nid).limit(1)):
            return d
    if user.role == "volunteer" and d.task and (d.task.volunteer_id == user.id or d.task.status == "open"):
        return d
    raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Donation not found")


@router.post("", response_model=DonationOut, status_code=status.HTTP_201_CREATED)
def create_donation(body: DonationCreate, user: User = Depends(require_roles("donor")), db: Session = Depends(get_db)):
    now = utcnow()
    expires_at = now + timedelta(hours=body.usable_life_hours)
    if body.pickup_end <= now:
        raise HTTPException(422, detail="Pickup window must end in the future")
    if body.pickup_start >= expires_at:
        raise HTTPException(422,
                            detail="Pickup window must start before the food's usable life ends")
    if body.prepared_at and body.prepared_at > now + timedelta(minutes=5):
        raise HTTPException(422, detail="Preparation time cannot be in the future")
    d = Donation(
        donor_id=user.id,
        food_name=body.food_name.strip(),
        category=body.category,
        quantity=body.quantity,
        unit=body.unit,
        quantity_kg=body.quantity_kg,
        preparation_details=body.preparation_details,
        prepared_at=body.prepared_at,
        posted_at=now,
        usable_life_hours=body.usable_life_hours,
        expires_at=expires_at,
        pickup_address=body.pickup_address.strip(),
        latitude=body.latitude,
        longitude=body.longitude,
        pickup_start=body.pickup_start,
        pickup_end=min(body.pickup_end, expires_at),
        notes=body.notes,
        status="posted",
    )
    db.add(d)
    db.flush()
    audit(db, user.id, "donation_created", "donation", d.id, quantity_kg=d.quantity_kg, category=d.category)
    generate_matches(db, d, user.id, now)
    db.commit()
    db.refresh(d)
    return donation_out(d)


@router.get("", response_model=Page[DonationOut])
def list_my_donations(
    status_filter: Optional[str] = Query(None, alias="status"),
    page: int = 1,
    page_size: int = 20,
    user: User = Depends(require_roles("donor")),
    db: Session = Depends(get_db),
):
    stmt = select(Donation).where(Donation.donor_id == user.id)
    if status_filter:
        if status_filter not in DONATION_STATUSES:
            raise HTTPException(422, detail="Unknown status")
        stmt = stmt.where(Donation.status == status_filter)
    return paginate(db, stmt.order_by(Donation.created_at.desc()), page, page_size, donation_out)


@router.get("/summary")
def donor_summary(user: User = Depends(require_roles("donor")), db: Session = Depends(get_db)):
    rows = db.scalars(select(Donation).where(Donation.donor_id == user.id)).all()
    by_status: dict[str, int] = {s: 0 for s in DONATION_STATUSES}
    for r in rows:
        by_status[r.status] += 1
    return {
        "total": len(rows),
        "by_status": by_status,
        "kg_offered": round(sum(r.quantity_kg for r in rows), 2),
        "kg_delivered": round(sum(r.quantity_kg for r in rows if r.status == "delivered"), 2),
        "kg_in_progress": round(sum(r.quantity_kg for r in rows if r.status in ("accepted", "picked_up")), 2),
    }


@router.get("/{donation_id}", response_model=DonationOut)
def get_donation(donation_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return donation_out(get_visible_donation(db, donation_id, user))


@router.patch("/{donation_id}", response_model=DonationOut)
def update_donation(donation_id: int, body: DonationUpdate, user: User = Depends(require_roles("donor")),
                    db: Session = Depends(get_db)):
    d = db.get(Donation, donation_id)
    if d is None or d.donor_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Donation not found")
    if d.status not in ("posted", "matched"):
        raise HTTPException(status.HTTP_409_CONFLICT, detail=f"A {d.status} donation can no longer be edited")
    data = body.model_dump(exclude_unset=True)
    start = data.get("pickup_start", d.pickup_start)
    end = data.get("pickup_end", d.pickup_end)
    if end <= start:
        raise HTTPException(422, detail="Pickup window end must be after its start")
    for k, v in data.items():
        setattr(d, k, v)
    audit(db, user.id, "donation_updated", "donation", d.id, fields=list(data))
    if {"pickup_start", "pickup_end"} & data.keys():
        generate_matches(db, d, user.id)
    db.commit()
    db.refresh(d)
    return donation_out(d)


@router.post("/{donation_id}/cancel", response_model=DonationOut)
def cancel(donation_id: int, user: User = Depends(require_roles("donor", "admin")), db: Session = Depends(get_db)):
    d = db.get(Donation, donation_id)
    if d is None or (user.role != "admin" and d.donor_id != user.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Donation not found")
    return donation_out(cancel_donation(db, d, user))


@router.post("/{donation_id}/image", response_model=DonationOut)
async def upload_image(donation_id: int, file: UploadFile = File(...), user: User = Depends(require_roles("donor")),
                       db: Session = Depends(get_db)):
    d = db.get(Donation, donation_id)
    if d is None or d.donor_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Donation not found")
    data = await file.read(config.MAX_IMAGE_BYTES + 1)
    if len(data) > config.MAX_IMAGE_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Image must be 2 MB or smaller")
    ext = _image_ext(data[:16])
    if ext is None:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Only JPEG, PNG or WebP images are allowed")
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}.{ext}"
    (config.UPLOAD_DIR / name).write_bytes(data)
    if d.image_path:
        old = config.UPLOAD_DIR / d.image_path
        if old.is_file():
            old.unlink()
    d.image_path = name
    db.commit()
    db.refresh(d)
    return donation_out(d)
