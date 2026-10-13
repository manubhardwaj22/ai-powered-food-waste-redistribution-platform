"""Operational statistics computed live from the database (admin dashboard)."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .database import utcnow
from .models import (
    DONATION_STATUSES,
    FOOD_CATEGORIES,
    DeliveryTask,
    Donation,
    MatchRecommendation,
    NGOProfile,
    Report,
    User,
)


def is_delayed(d: Donation, now) -> bool:
    """Accepted but not picked up after the pickup window closed."""
    return d.status == "accepted" and d.pickup_end < now


def platform_stats(db: Session) -> dict:
    now = utcnow()
    users_by_role = dict(db.execute(select(User.role, func.count(User.id)).group_by(User.role)).all())
    donations = db.scalars(select(Donation)).all()
    by_status = {s: 0 for s in DONATION_STATUSES}
    kg_by_category: dict[str, float] = defaultdict(float)
    for d in donations:
        by_status[d.status] += 1
        kg_by_category[FOOD_CATEGORIES.get(d.category, d.category)] += d.quantity_kg

    matched_states = ("accepted", "picked_up", "delivered")
    kg_offered = sum(d.quantity_kg for d in donations)
    kg_matched = sum(d.quantity_kg for d in donations if d.status in matched_states)
    kg_delivered = sum(d.quantity_kg for d in donations if d.status == "delivered")

    rec_status = dict(db.execute(select(MatchRecommendation.status, func.count(MatchRecommendation.id))
                                 .group_by(MatchRecommendation.status)).all())
    decided = rec_status.get("accepted", 0) + rec_status.get("rejected", 0)
    avg_accepted_score = db.scalar(select(func.avg(MatchRecommendation.score))
                                   .where(MatchRecommendation.status == "accepted"))
    avg_accepted_distance = db.scalar(select(func.avg(MatchRecommendation.distance_km))
                                      .where(MatchRecommendation.status == "accepted"))
    task_status = dict(db.execute(select(DeliveryTask.status, func.count(DeliveryTask.id))
                                  .group_by(DeliveryTask.status)).all())

    # Daily activity for the last 14 days (posted vs delivered).
    start = (now - timedelta(days=13)).date()
    days = [(start + timedelta(days=i)).isoformat() for i in range(14)]
    posted = Counter(d.posted_at.date().isoformat() for d in donations if d.posted_at.date() >= start)
    delivered = Counter(
        t.delivered_at.date().isoformat()
        for t in db.scalars(select(DeliveryTask).where(DeliveryTask.delivered_at.is_not(None))).all()
        if t.delivered_at.date() >= start
    )

    return {
        "generated_at": now.isoformat() + "Z",
        "users_by_role": {r: users_by_role.get(r, 0) for r in ("donor", "ngo", "volunteer", "admin")},
        "donations_by_status": by_status,
        "delayed": sum(1 for d in donations if is_delayed(d, now)),
        "pending": by_status["posted"] + by_status["matched"],
        "kg_offered": round(kg_offered, 2),
        "kg_matched": round(kg_matched, 2),
        "kg_delivered": round(kg_delivered, 2),
        "match_rate_pct": round(100 * kg_matched / kg_offered, 2) if kg_offered else 0.0,
        "kg_by_category": {k: round(v, 2) for k, v in kg_by_category.items()},
        "recommendations": rec_status,
        "ngo_acceptance_rate_pct": round(100 * rec_status.get("accepted", 0) / decided, 2) if decided else None,
        "avg_accepted_score": round(avg_accepted_score, 4) if avg_accepted_score is not None else None,
        "avg_accepted_distance_km": round(avg_accepted_distance, 2) if avg_accepted_distance is not None else None,
        "tasks_by_status": task_status,
        "completed_pickups": task_status.get("picked_up", 0) + task_status.get("delivered", 0),
        "completed_deliveries": task_status.get("delivered", 0),
        "ngo_count": db.scalar(select(func.count(NGOProfile.id))) or 0,
        "open_reports": db.scalar(select(func.count(Report.id)).where(Report.status == "open")) or 0,
        "activity": {"days": days, "posted": [posted.get(d, 0) for d in days],
                     "delivered": [delivered.get(d, 0) for d in days]},
    }
