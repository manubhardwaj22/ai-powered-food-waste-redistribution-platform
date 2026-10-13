"""Donation lifecycle and match-assignment services.

All state changes go through this module so the transition rules, capacity
accounting, notifications and audit trail stay consistent no matter which
route triggers them.

Lifecycle:  posted -> matched -> accepted -> picked_up -> delivered
            (posted | matched | accepted) -> cancelled | expired
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from . import config, matching
from .database import utcnow
from .models import (
    FOOD_CATEGORIES,
    DeliveryTask,
    Donation,
    MatchRecommendation,
    NGOProfile,
    User,
    VolunteerProfile,
)
from .notifications import audit, notify, notify_many

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "posted": {"matched", "cancelled", "expired"},
    "matched": {"posted", "accepted", "cancelled", "expired"},
    "accepted": {"picked_up", "cancelled", "expired"},
    "picked_up": {"delivered"},
    "delivered": set(),
    "cancelled": set(),
    "expired": set(),
}


def conflict(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, detail=detail)


def check_transition(current: str, new: str) -> None:
    if new not in ALLOWED_TRANSITIONS.get(current, set()):
        raise conflict(f"Cannot change donation status from '{current}' to '{new}'")


def category_label(key: str) -> str:
    return FOOD_CATEGORIES.get(key, key)


# ---------------------------------------------------------------------------
# Adapters from ORM rows to the pure matching engine
# ---------------------------------------------------------------------------
def donation_input(d: Donation) -> matching.DonationInput:
    return matching.DonationInput(
        id=d.id,
        category=d.category,
        quantity_kg=d.quantity_kg,
        latitude=d.latitude,
        longitude=d.longitude,
        expires_at=d.expires_at,
        pickup_start=d.pickup_start,
        pickup_end=d.pickup_end,
        status=d.status,
    )


def ngo_input(n: NGOProfile) -> matching.NGOInput:
    return matching.NGOInput(
        id=n.id,
        name=n.org_name,
        latitude=n.latitude,
        longitude=n.longitude,
        capacity_kg=n.capacity_kg,
        demand_kg=n.demand_kg,
        priority=n.priority,
        categories=n.categories,
        active=bool(n.user and n.user.is_active),
    )


def volunteer_inputs(db: Session) -> list[matching.VolunteerInput]:
    rows = db.scalars(
        select(VolunteerProfile).join(User).where(User.is_active.is_(True), VolunteerProfile.is_available.is_(True))
    ).all()
    return [
        matching.VolunteerInput(
            id=v.user_id,
            latitude=v.latitude,
            longitude=v.longitude,
            is_available=v.is_available,
            vehicle_capacity_kg=v.vehicle_capacity_kg,
            max_distance_km=v.max_distance_km,
        )
        for v in rows
    ]


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------
def generate_matches(db: Session, donation: Donation, actor_id: Optional[int], now: Optional[datetime] = None) -> list[MatchRecommendation]:
    """(Re)compute ranked recommendations for an open donation and persist them.

    Previously proposed recommendations are superseded; NGOs that already
    declined this donation are excluded. Only NGOs newly entering the list are
    notified, to avoid repeated alerts.
    """
    now = now or utcnow()
    if donation.status not in ("posted", "matched"):
        raise conflict(f"Donation is {donation.status}; it can no longer be matched")

    existing = db.scalars(select(MatchRecommendation).where(MatchRecommendation.donation_id == donation.id)).all()
    declined = {m.ngo_id for m in existing if m.status == "rejected"}
    previously_proposed = {m.ngo_id for m in existing if m.status == "proposed"}
    for m in existing:
        if m.status == "proposed":
            m.status = "superseded"

    ngos = db.scalars(select(NGOProfile).join(User)).all()
    vols = volunteer_inputs(db) if config.REQUIRE_VOLUNTEER_FEASIBILITY else None
    result = matching.rank_candidates(
        donation_input(donation),
        [ngo_input(n) for n in ngos],
        now,
        max_distance_km=config.MAX_MATCH_DISTANCE_KM,
        limit=config.MAX_RECOMMENDATIONS,
        volunteers=vols,
        exclude_ngo_ids=declined,
    )

    created: list[MatchRecommendation] = []
    for c in result.candidates:
        rec = MatchRecommendation(
            donation_id=donation.id,
            ngo_id=c.ngo_id,
            rank=c.rank,
            score=round(c.score, 6),
            freshness=round(c.freshness, 6),
            proximity=round(c.proximity, 6),
            capacity_fit=round(c.capacity_fit, 6),
            demand_fit=round(c.demand_fit, 6),
            priority=round(c.priority, 6),
            distance_km=c.distance_km,
            explanation=c.explanation,
            status="proposed",
            created_at=now,
        )
        db.add(rec)
        created.append(rec)

    new_status = "matched" if created else "posted"
    if donation.status != new_status:
        check_transition(donation.status, new_status)
        donation.status = new_status

    ngo_by_id = {n.id: n for n in ngos}
    link = f"match-details.html?id={donation.id}"
    for rec in created:
        if rec.ngo_id not in previously_proposed:
            n = ngo_by_id[rec.ngo_id]
            notify(
                db,
                n.user_id,
                "new_offer",
                f"New eligible donation: {donation.food_name} ({donation.quantity_kg:g} kg, "
                f"{rec.distance_km:.1f} km away). Match score {rec.score:.3f}.",
                link,
            )
    if created and not previously_proposed:
        notify(db, donation.donor_id, "match_ready",
               f"{len(created)} NGO recommendation(s) are ready for '{donation.food_name}'.", link)
    audit(db, actor_id, "matching_run", "donation", donation.id,
          candidates=len(created), reason=result.reason or None,
          top=[(c.ngo_id, round(c.score, 4)) for c in result.candidates[:3]])
    db.flush()
    return created


def refresh_open_matches(db: Session, actor_id: Optional[int] = None) -> int:
    """Re-run matching for every open donation (e.g. after an NGO updates capacity)."""
    now = utcnow()
    open_rows = db.scalars(select(Donation).where(Donation.status.in_(("posted", "matched")), Donation.expires_at > now)).all()
    for d in open_rows:
        generate_matches(db, d, actor_id, now)
    return len(open_rows)


# ---------------------------------------------------------------------------
# NGO decision on a recommendation
# ---------------------------------------------------------------------------
def accept_match(db: Session, match_id: int, user: User) -> MatchRecommendation:
    """Accept a proposed match atomically.

    Concurrency protection: the donation status and NGO capacity are changed
    with conditional UPDATE statements (compare-and-set). If another request
    already accepted the donation, or capacity was consumed meanwhile, the
    UPDATE affects 0 rows and the whole transaction is rolled back with 409.
    """
    now = utcnow()
    rec = db.get(MatchRecommendation, match_id)
    if rec is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Match not found")
    ngo = rec.ngo
    if user.role != "ngo" or ngo.user_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Only the recommended NGO can accept this match")
    if rec.status != "proposed":
        raise conflict(f"This recommendation is already {rec.status}")
    d = rec.donation
    if d.status not in ("posted", "matched"):
        raise conflict(f"Donation is already {d.status}")

    # Re-validate hard constraints with current data (not the stale scores).
    why = matching.validate_donation(donation_input(d), now)
    if why:
        raise conflict(f"Donation cannot be accepted: {why}")
    if d.category not in ngo.categories:
        raise conflict("Your organisation does not accept this food category")
    if ngo.capacity_kg < d.quantity_kg:
        raise conflict(f"Insufficient available capacity ({ngo.capacity_kg:g} kg < {d.quantity_kg:g} kg)")
    if ngo.demand_kg <= 0:
        raise conflict("Your unmet demand is zero; update demand before accepting")

    try:
        claimed = db.execute(
            update(Donation)
            .where(Donation.id == d.id, Donation.status.in_(("posted", "matched")))
            .values(status="accepted", ngo_id=ngo.id, updated_at=now)
            .execution_options(synchronize_session=False)
        ).rowcount
        if claimed != 1:
            raise conflict("Donation was just accepted by another organisation")
        allocated_demand = min(d.quantity_kg, ngo.demand_kg)
        reserved = db.execute(
            update(NGOProfile)
            .where(NGOProfile.id == ngo.id, NGOProfile.capacity_kg >= d.quantity_kg)
            .values(capacity_kg=NGOProfile.capacity_kg - d.quantity_kg,
                    demand_kg=func.max(NGOProfile.demand_kg - allocated_demand, 0.0),
                    updated_at=now)
            .execution_options(synchronize_session=False)
        ).rowcount
        if reserved != 1:
            raise conflict("Capacity changed; not enough capacity remains")
        db.execute(
            update(Donation).where(Donation.id == d.id).values(allocated_demand_kg=allocated_demand)
            .execution_options(synchronize_session=False)
        )
        db.refresh(d)
        db.refresh(ngo)

        rec.status = "accepted"
        rec.decided_at = now
        rec.decided_by = user.id
        for other in db.scalars(select(MatchRecommendation).where(
                MatchRecommendation.donation_id == d.id, MatchRecommendation.id != rec.id,
                MatchRecommendation.status == "proposed")).all():
            other.status = "superseded"

        task = DeliveryTask(donation_id=d.id, ngo_id=ngo.id, status="open", distance_km=rec.distance_km, created_at=now)
        db.add(task)
        db.flush()

        link = f"match-details.html?id={d.id}"
        notify(db, d.donor_id, "ngo_accepted",
               f"{ngo.org_name} accepted '{d.food_name}'. A volunteer pickup task has been created.", link)
        notify(db, user.id, "ngo_accepted",
               f"You accepted '{d.food_name}' ({d.quantity_kg:g} kg). Please verify food condition on arrival.", link)
        _notify_eligible_volunteers(db, d)
        audit(db, user.id, "match_accepted", "donation", d.id, match_id=rec.id, ngo_id=ngo.id,
              quantity_kg=d.quantity_kg, allocated_demand_kg=allocated_demand)
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    return rec


def reject_match(db: Session, match_id: int, user: User, reason: Optional[str]) -> MatchRecommendation:
    now = utcnow()
    rec = db.get(MatchRecommendation, match_id)
    if rec is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Match not found")
    if user.role != "ngo" or rec.ngo.user_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Only the recommended NGO can reject this match")
    if rec.status != "proposed":
        raise conflict(f"This recommendation is already {rec.status}")
    d = rec.donation
    rec.status = "rejected"
    rec.decided_at = now
    rec.decided_by = user.id
    notify(db, d.donor_id, "ngo_rejected",
           f"{rec.ngo.org_name} declined '{d.food_name}'" + (f": {reason}" if reason else "."),
           f"match-details.html?id={d.id}")
    audit(db, user.id, "match_rejected", "donation", d.id, match_id=rec.id, reason=reason)
    db.flush()
    remaining = db.scalar(select(MatchRecommendation.id).where(
        MatchRecommendation.donation_id == d.id, MatchRecommendation.status == "proposed").limit(1))
    if remaining is None and d.status in ("posted", "matched"):
        generate_matches(db, d, user.id, now)
    db.commit()
    return rec


# ---------------------------------------------------------------------------
# Releasing reservations (cancel / expire)
# ---------------------------------------------------------------------------
def _release_reservation(db: Session, d: Donation) -> None:
    if d.ngo_id is None or d.status != "accepted":
        return
    db.execute(
        update(NGOProfile).where(NGOProfile.id == d.ngo_id)
        .values(capacity_kg=NGOProfile.capacity_kg + d.quantity_kg,
                demand_kg=NGOProfile.demand_kg + (d.allocated_demand_kg or 0.0))
        .execution_options(synchronize_session=False)
    )
    d.allocated_demand_kg = 0.0


def _close_open_items(db: Session, d: Donation) -> list[int]:
    """Supersede proposed matches and cancel the task. Returns users to notify."""
    users: list[int] = []
    for m in db.scalars(select(MatchRecommendation).where(
            MatchRecommendation.donation_id == d.id, MatchRecommendation.status == "proposed")).all():
        m.status = "superseded"
    if d.task and d.task.status in ("open", "accepted"):
        if d.task.volunteer_id:
            users.append(d.task.volunteer_id)
        d.task.status = "cancelled"
    if d.ngo is not None:
        users.append(d.ngo.user_id)
    return users


def cancel_donation(db: Session, d: Donation, actor: User) -> Donation:
    if actor.role != "admin" and d.donor_id != actor.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="You can only cancel your own donations")
    check_transition(d.status, "cancelled")
    _release_reservation(db, d)
    to_notify = _close_open_items(db, d)
    d.status = "cancelled"
    notify_many(db, to_notify, "donation_cancelled", f"Donation '{d.food_name}' was cancelled by the donor.",
                f"match-details.html?id={d.id}")
    audit(db, actor.id, "donation_cancelled", "donation", d.id)
    db.commit()
    db.refresh(d)
    return d


def run_maintenance(db: Session, now: Optional[datetime] = None) -> dict[str, int]:
    """Expire overdue offers and send expiry / overdue warnings (idempotent)."""
    now = now or utcnow()
    stats = {"expired": 0, "warned": 0, "overdue": 0}

    for d in db.scalars(select(Donation).where(
            Donation.status.in_(("posted", "matched", "accepted")), Donation.expires_at <= now)).all():
        _release_reservation(db, d)
        to_notify = _close_open_items(db, d)
        d.status = "expired"
        notify_many(db, [d.donor_id, *to_notify], "expired",
                    f"Donation '{d.food_name}' expired before it could be delivered.",
                    f"match-details.html?id={d.id}")
        audit(db, None, "donation_expired", "donation", d.id)
        stats["expired"] += 1

    soon = db.scalars(select(Donation).where(
        Donation.status.in_(("posted", "matched", "accepted")), Donation.expiry_warned.is_(False),
        Donation.expires_at > now)).all()
    for d in soon:
        hours = (d.expires_at - now).total_seconds() / 3600
        if hours <= config.EXPIRY_WARNING_HOURS:
            users = [d.donor_id]
            if d.ngo is not None:
                users.append(d.ngo.user_id)
            if d.task and d.task.volunteer_id:
                users.append(d.task.volunteer_id)
            notify_many(db, users, "expiring_soon",
                        f"'{d.food_name}' has about {hours:.1f} h of usable life left.",
                        f"match-details.html?id={d.id}")
            d.expiry_warned = True
            stats["warned"] += 1

    overdue = db.scalars(select(Donation).where(
        Donation.status == "accepted", Donation.overdue_warned.is_(False), Donation.pickup_end < now)).all()
    for d in overdue:
        users = [d.donor_id] + ([d.ngo.user_id] if d.ngo else [])
        if d.task and d.task.volunteer_id:
            users.append(d.task.volunteer_id)
        notify_many(db, users, "overdue", f"Pickup for '{d.food_name}' is overdue (window has closed).",
                    f"match-details.html?id={d.id}")
        d.overdue_warned = True
        stats["overdue"] += 1

    db.commit()
    return stats


# ---------------------------------------------------------------------------
# Volunteer tasks
# ---------------------------------------------------------------------------
def task_eligibility(task: DeliveryTask, v: VolunteerProfile) -> tuple[bool, Optional[str], Optional[float]]:
    d = task.donation
    try:
        dist = matching.haversine_km(v.latitude, v.longitude, d.latitude, d.longitude)
    except ValueError:
        return False, "your location is invalid", None
    if not v.is_available:
        return False, "you are marked unavailable", dist
    if v.vehicle_capacity_kg < d.quantity_kg:
        return False, f"vehicle capacity {v.vehicle_capacity_kg:g} kg is below {d.quantity_kg:g} kg", dist
    if dist > v.max_distance_km:
        return False, f"pickup is {dist:.1f} km away (your limit is {v.max_distance_km:g} km)", dist
    return True, None, dist


def _notify_eligible_volunteers(db: Session, d: Donation) -> None:
    vols = db.scalars(select(VolunteerProfile).join(User).where(
        User.is_active.is_(True), VolunteerProfile.is_available.is_(True))).all()
    for v in vols:
        if v.vehicle_capacity_kg < d.quantity_kg:
            continue
        try:
            dist = matching.haversine_km(v.latitude, v.longitude, d.latitude, d.longitude)
        except ValueError:
            continue
        if dist <= v.max_distance_km:
            notify(db, v.user_id, "new_task",
                   f"New pickup task: {d.food_name} ({d.quantity_kg:g} kg), {dist:.1f} km from you.",
                   "volunteer-dashboard.html")


def accept_task(db: Session, task_id: int, user: User) -> DeliveryTask:
    now = utcnow()
    task = db.get(DeliveryTask, task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Task not found")
    v = user.volunteer_profile
    if v is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Volunteer profile required")
    if task.status != "open":
        raise conflict(f"Task is already {task.status}")
    if task.donation.status != "accepted":
        raise conflict(f"Donation is {task.donation.status}")
    ok, why, _ = task_eligibility(task, v)
    if not ok:
        raise conflict(f"You are not eligible for this task: {why}")
    claimed = db.execute(
        update(DeliveryTask).where(DeliveryTask.id == task.id, DeliveryTask.status == "open")
        .values(status="accepted", volunteer_id=user.id, accepted_at=now)
        .execution_options(synchronize_session=False)
    ).rowcount
    if claimed != 1:
        db.rollback()
        raise conflict("Another volunteer has just accepted this task")
    db.refresh(task)
    d = task.donation
    notify_many(db, [d.donor_id, task.ngo.user_id], "volunteer_accepted",
                f"Volunteer {user.full_name} will pick up '{d.food_name}'.", f"match-details.html?id={d.id}")
    audit(db, user.id, "task_accepted", "delivery_task", task.id, donation_id=d.id)
    db.commit()
    return task


def update_task_status(db: Session, task_id: int, user: User, new_status: str) -> DeliveryTask:
    now = utcnow()
    task = db.get(DeliveryTask, task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Task not found")
    if task.volunteer_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Only the assigned volunteer can update this task")
    d = task.donation
    if new_status == "picked_up":
        if task.status != "accepted":
            raise conflict(f"Task must be 'accepted' to mark it picked up (it is '{task.status}')")
        check_transition(d.status, "picked_up")
        task.status, task.picked_up_at, d.status = "picked_up", now, "picked_up"
        msg = f"'{d.food_name}' has been picked up by {user.full_name}."
    elif new_status == "delivered":
        if task.status != "picked_up":
            raise conflict(f"Task must be 'picked_up' to mark it delivered (it is '{task.status}')")
        check_transition(d.status, "delivered")
        task.status, task.delivered_at, d.status = "delivered", now, "delivered"
        msg = (f"'{d.food_name}' was delivered to {task.ngo.org_name}. "
               "The receiving NGO should inspect the food before distribution.")
    else:  # pragma: no cover - schema restricts values
        raise conflict("Unsupported status")
    notify_many(db, [d.donor_id, task.ngo.user_id, user.id], f"task_{new_status}", msg, f"match-details.html?id={d.id}")
    audit(db, user.id, f"task_{new_status}", "delivery_task", task.id, donation_id=d.id)
    db.commit()
    return task
