"""Endpoints shared by every signed-in role: notifications, reports, metadata."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from ..models import FOOD_CATEGORIES, UNITS, Donation, Notification, Report, User
from ..notifications import audit, notify_many
from ..schemas import NotificationOut, ReportCreate, ReportOut

router = APIRouter(prefix="/api", tags=["common"])


@router.get("/meta")
def meta():
    """Food categories and units for building forms (public)."""
    return {
        "categories": [{"key": k, "label": v} for k, v in FOOD_CATEGORIES.items()],
        "units": list(UNITS),
    }


@router.get("/notifications")
def list_notifications(unread_only: bool = False, limit: int = 30,
                       user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    stmt = select(Notification).where(Notification.user_id == user.id)
    if unread_only:
        stmt = stmt.where(Notification.is_read.is_(False))
    rows = db.scalars(stmt.order_by(Notification.created_at.desc(), Notification.id.desc())
                      .limit(max(1, min(limit, 100)))).all()
    unread = db.scalar(select(func.count(Notification.id)).where(
        Notification.user_id == user.id, Notification.is_read.is_(False))) or 0
    return {"items": [NotificationOut.model_validate(n) for n in rows], "unread": unread}


@router.post("/notifications/{notification_id}/read", response_model=NotificationOut)
def mark_read(notification_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    n = db.get(Notification, notification_id)
    if n is None or n.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Notification not found")
    n.is_read = True
    db.commit()
    return NotificationOut.model_validate(n)


@router.post("/notifications/read-all")
def mark_all_read(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    count = db.execute(update(Notification).where(Notification.user_id == user.id, Notification.is_read.is_(False))
                       .values(is_read=True)).rowcount
    db.commit()
    return {"updated": count}


@router.post("/reports", response_model=ReportOut, status_code=status.HTTP_201_CREATED)
def create_report(body: ReportCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Flag a problematic donation or account for administrator review."""
    target = db.get(Donation if body.entity_type == "donation" else User, body.entity_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"{body.entity_type.title()} not found")
    dup = db.scalar(select(Report.id).where(Report.reporter_id == user.id, Report.entity_type == body.entity_type,
                                            Report.entity_id == body.entity_id, Report.status == "open"))
    if dup:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="You already have an open report for this item")
    r = Report(reporter_id=user.id, entity_type=body.entity_type, entity_id=body.entity_id, reason=body.reason)
    db.add(r)
    db.flush()
    admins = db.scalars(select(User.id).where(User.role == "admin", User.is_active.is_(True))).all()
    notify_many(db, admins, "report", f"New report on {body.entity_type} #{body.entity_id}: {body.reason[:120]}",
                "admin-dashboard.html#reports")
    audit(db, user.id, "report_created", body.entity_type, body.entity_id, report_id=r.id)
    db.commit()
    out = ReportOut.model_validate(r)
    out.reporter_name = user.full_name
    return out
