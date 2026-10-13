"""NGO / food-bank endpoints: profile, needs, recommended offers, impact."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import require_roles
from ..database import get_db
from ..models import Donation, MatchRecommendation, NGOProfile, User
from ..notifications import audit
from ..schemas import DonationOut, NGOOut, NGOUpdate, Page
from ..serializers import donation_out, match_out
from ..services import refresh_open_matches
from . import paginate

router = APIRouter(prefix="/api/ngo", tags=["ngo"])


def _profile(user: User) -> NGOProfile:
    if user.ngo_profile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="NGO profile not found")
    return user.ngo_profile


@router.get("/profile", response_model=NGOOut)
def get_profile(user: User = Depends(require_roles("ngo"))):
    return NGOOut.model_validate(_profile(user))


@router.patch("/profile", response_model=NGOOut)
def update_profile(body: NGOUpdate, user: User = Depends(require_roles("ngo")), db: Session = Depends(get_db)):
    p = _profile(user)
    data = body.model_dump(exclude_unset=True)
    before = {k: getattr(p, k) for k in ("capacity_kg", "demand_kg", "priority", "accepted_categories")}
    if "accepted_categories" in data:
        data["accepted_categories"] = ",".join(sorted(set(data["accepted_categories"])))
    for k, v in data.items():
        setattr(p, k, v)
    audit(db, user.id, "ngo_profile_updated", "ngo", p.id, before=before,
          after={k: getattr(p, k) for k in before})
    db.flush()
    refresh_open_matches(db, user.id)  # updated capacity/demand changes rankings
    db.commit()
    db.refresh(p)
    return NGOOut.model_validate(p)


@router.get("/recommendations")
def my_recommendations(user: User = Depends(require_roles("ngo")), db: Session = Depends(get_db)):
    """Donation offers currently proposed to this NGO, best score first."""
    p = _profile(user)
    rows = db.scalars(
        select(MatchRecommendation)
        .join(Donation, Donation.id == MatchRecommendation.donation_id)
        .where(MatchRecommendation.ngo_id == p.id, MatchRecommendation.status == "proposed",
               Donation.status.in_(("posted", "matched")))
        .order_by(MatchRecommendation.score.desc())
    ).all()
    return [{"match": match_out(m), "donation": donation_out(m.donation)} for m in rows]


@router.get("/donations", response_model=Page[DonationOut])
def my_donations(
    status_filter: Optional[str] = Query(None, alias="status"),
    page: int = 1,
    page_size: int = 20,
    user: User = Depends(require_roles("ngo")),
    db: Session = Depends(get_db),
):
    """Donations assigned to this NGO (accepted, picked up, delivered, cancelled, expired)."""
    p = _profile(user)
    stmt = select(Donation).where(Donation.ngo_id == p.id)
    if status_filter:
        stmt = stmt.where(Donation.status == status_filter)
    return paginate(db, stmt.order_by(Donation.updated_at.desc()), page, page_size, donation_out)


@router.get("/stats")
def impact(user: User = Depends(require_roles("ngo")), db: Session = Depends(get_db)):
    p = _profile(user)
    rows = db.scalars(select(Donation).where(Donation.ngo_id == p.id)).all()
    proposed_count = db.scalar(select(func.count(MatchRecommendation.id)).where(
        MatchRecommendation.ngo_id == p.id, MatchRecommendation.status == "proposed")) or 0
    delivered = [r for r in rows if r.status == "delivered"]
    return {
        "pending_offers": proposed_count,
        "accepted": sum(1 for r in rows if r.status == "accepted"),
        "in_transit": sum(1 for r in rows if r.status == "picked_up"),
        "delivered": len(delivered),
        "kg_received": round(sum(r.quantity_kg for r in delivered), 2),
        "kg_incoming": round(sum(r.quantity_kg for r in rows if r.status in ("accepted", "picked_up")), 2),
        "capacity_kg": p.capacity_kg,
        "demand_kg": p.demand_kg,
    }
