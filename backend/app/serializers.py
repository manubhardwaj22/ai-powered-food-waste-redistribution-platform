"""Convert ORM rows into response schemas (adds derived, display-friendly fields)."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from . import matching
from .database import utcnow
from .models import DeliveryTask, Donation, MatchRecommendation, NGOProfile, VolunteerProfile
from .schemas import DonationOut, MatchOut, NGOOut, TaskOut
from .services import category_label, task_eligibility


def remaining(d: Donation, now: Optional[datetime] = None) -> float:
    now = now or utcnow()
    return round((d.expires_at - now).total_seconds() / 3600.0, 2)


def donation_out(d: Donation, now: Optional[datetime] = None) -> DonationOut:
    out = DonationOut.model_validate(d)
    out.donor_name = d.donor.full_name if d.donor else None
    out.donor_org = d.donor.organization if d.donor else None
    out.category_label = category_label(d.category)
    out.remaining_hours = remaining(d, now) if d.status in ("posted", "matched", "accepted", "picked_up") else 0.0
    out.image_url = f"/uploads/{d.image_path}" if d.image_path else None
    out.ngo_name = d.ngo.org_name if d.ngo else None
    out.task_status = d.task.status if d.task else None
    return out


def match_out(m: MatchRecommendation) -> MatchOut:
    out = MatchOut.model_validate(m)
    out.ngo_name = m.ngo.org_name if m.ngo else None
    return out


def ngo_out(n: NGOProfile) -> NGOOut:
    return NGOOut.model_validate(n)


def task_out(t: DeliveryTask, viewer: Optional[VolunteerProfile] = None, include_contacts: bool = True) -> TaskOut:
    d = t.donation
    n = t.ngo
    out = TaskOut(
        id=t.id,
        donation_id=d.id,
        status=t.status,
        distance_km=round(t.distance_km, 2),
        volunteer_id=t.volunteer_id,
        volunteer_name=t.volunteer.full_name if t.volunteer else None,
        created_at=t.created_at,
        accepted_at=t.accepted_at,
        picked_up_at=t.picked_up_at,
        delivered_at=t.delivered_at,
        food_name=d.food_name,
        category=category_label(d.category),
        quantity_kg=d.quantity_kg,
        remaining_hours=remaining(d),
        pickup_address=d.pickup_address,
        pickup_lat=d.latitude,
        pickup_lon=d.longitude,
        pickup_start=d.pickup_start,
        pickup_end=d.pickup_end,
        ngo_name=n.org_name,
        ngo_address=n.address,
        ngo_lat=n.latitude,
        ngo_lon=n.longitude,
    )
    if include_contacts:
        out.donor_name = d.donor.full_name
        out.donor_phone = d.donor.phone
        out.ngo_phone = n.contact_phone or (n.user.phone if n.user else None)
    if viewer is not None:
        ok, why, dist = task_eligibility(t, viewer)
        out.eligible, out.ineligible_reason = ok, why
        out.distance_from_you_km = round(dist, 2) if dist is not None else None
    return out


__all__ = ["donation_out", "match_out", "ngo_out", "task_out", "remaining", "matching"]
