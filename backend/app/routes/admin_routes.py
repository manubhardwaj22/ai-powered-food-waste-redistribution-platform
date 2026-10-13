"""Administrator endpoints. Every route requires role == 'admin' on the server."""
from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import analytics, benchmark, config
from ..auth import require_roles
from ..database import get_db, utcnow
from ..models import (
    DONATION_STATUSES,
    AuditLog,
    Donation,
    MatchRecommendation,
    NGOProfile,
    Report,
    User,
)
from ..notifications import audit
from ..schemas import (
    AuditOut,
    DonationOut,
    MatchOut,
    NGOOut,
    Page,
    ReportOut,
    ReportResolve,
    UserActiveUpdate,
    UserOut,
)
from ..serializers import donation_out, match_out
from ..services import cancel_donation, run_maintenance
from . import paginate

router = APIRouter(prefix="/api/admin", tags=["admin"])
Admin = Depends(require_roles("admin"))
RESULTS_PATH = config.DATA_DIR / "benchmark_results.json"


@router.get("/stats")
def stats(_: User = Admin, db: Session = Depends(get_db)):
    return analytics.platform_stats(db)


@router.get("/users", response_model=Page[UserOut])
def users(role: Optional[str] = None, page: int = 1, page_size: int = 25, _: User = Admin,
          db: Session = Depends(get_db)):
    stmt = select(User)
    if role:
        stmt = stmt.where(User.role == role)
    return paginate(db, stmt.order_by(User.created_at.desc()), page, page_size, UserOut.model_validate)


@router.patch("/users/{user_id}/active", response_model=UserOut)
def set_active(user_id: int, body: UserActiveUpdate, admin: User = Admin, db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="User not found")
    if u.id == admin.id and not body.is_active:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="You cannot deactivate your own account")
    u.is_active = body.is_active
    audit(db, admin.id, "user_activated" if body.is_active else "user_deactivated", "user", u.id)
    db.commit()
    return UserOut.model_validate(u)


@router.get("/donations", response_model=Page[DonationOut])
def donations(status_filter: Optional[str] = Query(None, alias="status"), delayed: bool = False,
              page: int = 1, page_size: int = 25, _: User = Admin, db: Session = Depends(get_db)):
    stmt = select(Donation)
    if status_filter:
        if status_filter not in DONATION_STATUSES:
            raise HTTPException(422, detail="Unknown status")
        stmt = stmt.where(Donation.status == status_filter)
    if delayed:
        stmt = stmt.where(Donation.status == "accepted", Donation.pickup_end < utcnow())
    return paginate(db, stmt.order_by(Donation.created_at.desc()), page, page_size, donation_out)


@router.post("/donations/{donation_id}/cancel", response_model=DonationOut)
def admin_cancel(donation_id: int, admin: User = Admin, db: Session = Depends(get_db)):
    d = db.get(Donation, donation_id)
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Donation not found")
    return donation_out(cancel_donation(db, d, admin))


@router.get("/ngos", response_model=list[NGOOut])
def ngos(_: User = Admin, db: Session = Depends(get_db)):
    return [NGOOut.model_validate(n) for n in db.scalars(select(NGOProfile).order_by(NGOProfile.org_name)).all()]


@router.get("/matches", response_model=Page[MatchOut])
def matches(status_filter: Optional[str] = Query(None, alias="status"), page: int = 1, page_size: int = 25,
            _: User = Admin, db: Session = Depends(get_db)):
    stmt = select(MatchRecommendation)
    if status_filter:
        stmt = stmt.where(MatchRecommendation.status == status_filter)
    return paginate(db, stmt.order_by(MatchRecommendation.created_at.desc(), MatchRecommendation.rank),
                    page, page_size, match_out)


@router.get("/audit", response_model=Page[AuditOut])
def audit_log(action: Optional[str] = None, page: int = 1, page_size: int = 30, _: User = Admin,
              db: Session = Depends(get_db)):
    stmt = select(AuditLog)
    if action:
        stmt = stmt.where(AuditLog.action == action)

    def conv(a: AuditLog) -> AuditOut:
        out = AuditOut.model_validate(a)
        if a.actor_id:
            u = db.get(User, a.actor_id)
            out.actor_name = u.full_name if u else None
        return out

    return paginate(db, stmt.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()), page, page_size, conv)


@router.get("/reports", response_model=list[ReportOut])
def reports(status_filter: Optional[str] = Query("open", alias="status"), _: User = Admin,
            db: Session = Depends(get_db)):
    stmt = select(Report)
    if status_filter:
        stmt = stmt.where(Report.status == status_filter)
    out = []
    for r in db.scalars(stmt.order_by(Report.created_at.desc())).all():
        o = ReportOut.model_validate(r)
        o.reporter_name = r.reporter.full_name
        out.append(o)
    return out


@router.post("/reports/{report_id}/resolve", response_model=ReportOut)
def resolve_report(report_id: int, body: ReportResolve, admin: User = Admin, db: Session = Depends(get_db)):
    r = db.get(Report, report_id)
    if r is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Report not found")
    if r.status != "open":
        raise HTTPException(status.HTTP_409_CONFLICT, detail=f"Report is already {r.status}")
    if body.deactivate_user:
        target_id = r.entity_id if r.entity_type == "user" else (db.get(Donation, r.entity_id).donor_id)
        target = db.get(User, target_id)
        if target and target.role != "admin":
            target.is_active = False
            audit(db, admin.id, "user_deactivated", "user", target.id, report_id=r.id)
    if body.cancel_donation and r.entity_type == "donation":
        d = db.get(Donation, r.entity_id)
        if d and d.status in ("posted", "matched", "accepted"):
            cancel_donation(db, d, admin)
    r.status = body.status
    r.resolution_note = body.resolution_note
    r.resolved_at = utcnow()
    audit(db, admin.id, f"report_{body.status}", r.entity_type, r.entity_id, report_id=r.id)
    db.commit()
    o = ReportOut.model_validate(r)
    o.reporter_name = r.reporter.full_name
    return o


@router.post("/maintenance/run")
def maintenance(admin: User = Admin, db: Session = Depends(get_db)):
    """Run the expiry / warning sweep now (it also runs in the background)."""
    result = run_maintenance(db)
    audit(db, admin.id, "maintenance_run", "system", None, **result)
    db.commit()
    return result


@router.get("/benchmark")
def latest_benchmark(_: User = Admin):
    if not RESULTS_PATH.exists():
        return {"available": False}
    return {"available": True, **json.loads(RESULTS_PATH.read_text())}


@router.post("/benchmark/run")
def run_benchmark(admin: User = Admin, db: Session = Depends(get_db)):
    """Regenerate the synthetic dataset (seed 7), evaluate all four methods and redraw charts."""
    res = benchmark.run_and_save(RESULTS_PATH, config.CHARTS_DIR)
    audit(db, admin.id, "benchmark_run", "system", None,
          proposed=res["methods"]["proposed"]["quantity_fulfillment_pct"])
    db.commit()
    return {"available": True, **res}
