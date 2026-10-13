"""Explainable, AI-assisted weighted scoring engine for donor -> NGO matching.

This module implements the hybrid weighted scoring model from the project
report. It is a transparent multi-criteria decision algorithm, NOT a trained
machine-learning model: every recommendation can be traced back to five
named components and five fixed weights.

For donation i and NGO j:

    Freshness urgency     F_i  = 1 - min(T_i, 24) / 24          (T_i = remaining life, hours)
    Geographic proximity  G_ij = exp(-D_ij / 5)                  (D_ij = distance, km)
    Capacity fit          C_ij = min(q_i, c_j) / max(q_i, c_j)   (q_i = quantity, c_j = available capacity)
    Demand fit            Q_ij = min(q_i, d_j) / max(q_i, d_j)   (d_j = unmet demand)
    Recipient priority    P_j  in [0, 1]

    S_ij = w_F F_i + w_G G_ij + w_C C_ij + w_Q Q_ij + w_P P_j

The functions here are pure (no database access) so they can be reused by the
live API and by the synthetic benchmark in `benchmark.py`.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable, Optional, Sequence

# ---------------------------------------------------------------------------
# Weights reported in the project report (sum = 1.0000)
# ---------------------------------------------------------------------------
W_FRESHNESS = 0.0714
W_PROXIMITY = 0.7280
W_CAPACITY = 0.0654
W_DEMAND = 0.0464
W_PRIORITY = 0.0888

WEIGHTS = {
    "freshness": W_FRESHNESS,
    "proximity": W_PROXIMITY,
    "capacity_fit": W_CAPACITY,
    "demand_fit": W_DEMAND,
    "priority": W_PRIORITY,
}

FRESHNESS_HORIZON_HOURS = 24.0  # T_i is capped at 24 h in F_i
PROXIMITY_SCALE_KM = 5.0  # distance decay constant in G_ij
EARTH_RADIUS_KM = 6371.0088


# ---------------------------------------------------------------------------
# Safe numeric helpers
# ---------------------------------------------------------------------------
def _finite(x: Optional[float]) -> bool:
    return x is not None and isinstance(x, (int, float)) and math.isfinite(x)


def _clamp01(x: float) -> float:
    return 0.0 if x < 0 else 1.0 if x > 1 else x


def valid_coordinates(lat: Optional[float], lon: Optional[float]) -> bool:
    return _finite(lat) and _finite(lon) and -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometres between two WGS-84 points.

    Raises ValueError for invalid coordinates so callers can treat the pair as
    infeasible instead of crashing or silently scoring garbage.
    """
    if not (valid_coordinates(lat1, lon1) and valid_coordinates(lat2, lon2)):
        raise ValueError("invalid coordinates")
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


# ---------------------------------------------------------------------------
# The five scoring components
# ---------------------------------------------------------------------------
def freshness_urgency(remaining_hours: float) -> float:
    """F_i = 1 - min(T_i, 24)/24. Shorter remaining life -> higher urgency.

    Negative / invalid T_i is treated as 0 h (maximum urgency); expired offers
    are removed earlier by the feasibility filter.
    """
    t = remaining_hours if _finite(remaining_hours) else 0.0
    t = max(0.0, t)
    return _clamp01(1.0 - min(t, FRESHNESS_HORIZON_HOURS) / FRESHNESS_HORIZON_HOURS)


def geographic_proximity(distance_km: float) -> float:
    """G_ij = exp(-D_ij / 5). 0 km -> 1.0, 5 km -> 0.368, 15 km -> 0.050."""
    if not _finite(distance_km) or distance_km < 0:
        return 0.0
    return math.exp(-distance_km / PROXIMITY_SCALE_KM)


def ratio_fit(a: float, b: float) -> float:
    """min(a, b) / max(a, b), defined as 0 when either side is <= 0 or invalid.

    Used for both capacity fit C_ij and demand fit Q_ij. A value of 1.0 means
    the donation quantity and the NGO's capacity/demand are equal; values near
    0 mean a large mismatch in either direction.
    """
    if not (_finite(a) and _finite(b)) or a <= 0 or b <= 0:
        return 0.0
    return min(a, b) / max(a, b)


def capacity_fit(quantity_kg: float, capacity_kg: float) -> float:
    return ratio_fit(quantity_kg, capacity_kg)


def demand_fit(quantity_kg: float, demand_kg: float) -> float:
    return ratio_fit(quantity_kg, demand_kg)


def recipient_priority(priority: float) -> float:
    return _clamp01(priority) if _finite(priority) else 0.0


def weighted_score(f: float, g: float, c: float, q: float, p: float) -> float:
    """S_ij = w_F F + w_G G + w_C C + w_Q Q + w_P P."""
    return W_FRESHNESS * f + W_PROXIMITY * g + W_CAPACITY * c + W_DEMAND * q + W_PRIORITY * p


# ---------------------------------------------------------------------------
# Inputs / outputs
# ---------------------------------------------------------------------------
@dataclass
class DonationInput:
    id: int
    category: str
    quantity_kg: float
    latitude: float
    longitude: float
    expires_at: datetime
    pickup_start: datetime
    pickup_end: datetime
    status: str = "posted"


@dataclass
class NGOInput:
    id: int
    name: str
    latitude: float
    longitude: float
    capacity_kg: float
    demand_kg: float
    priority: float
    categories: Sequence[str]
    active: bool = True


@dataclass
class VolunteerInput:
    id: int
    latitude: float
    longitude: float
    is_available: bool
    vehicle_capacity_kg: float
    max_distance_km: float


@dataclass
class Candidate:
    ngo_id: int
    ngo_name: str
    distance_km: float
    freshness: float
    proximity: float
    capacity_fit: float
    demand_fit: float
    priority: float
    score: float
    explanation: str = ""
    rank: int = 0

    def components(self) -> dict[str, float]:
        return {
            "freshness": self.freshness,
            "proximity": self.proximity,
            "capacity_fit": self.capacity_fit,
            "demand_fit": self.demand_fit,
            "priority": self.priority,
        }


@dataclass
class MatchResult:
    donation_id: int
    valid: bool
    reason: str = ""
    candidates: list[Candidate] = field(default_factory=list)
    rejected: dict[int, str] = field(default_factory=dict)  # ngo_id -> reason


# ---------------------------------------------------------------------------
# Step 1: validate the donation record
# ---------------------------------------------------------------------------
def remaining_hours(d: DonationInput, now: datetime) -> float:
    return (d.expires_at - now).total_seconds() / 3600.0


def validate_donation(d: DonationInput, now: datetime) -> Optional[str]:
    """Return a reason string if the donation cannot be matched, else None."""
    if d.status not in ("posted", "matched"):
        return f"donation is {d.status}"
    if not _finite(d.quantity_kg) or d.quantity_kg <= 0:
        return "invalid quantity"
    if not valid_coordinates(d.latitude, d.longitude):
        return "invalid pickup coordinates"
    if remaining_hours(d, now) <= 0:
        return "donation has expired"
    if d.pickup_end <= now:
        return "pickup window has closed"
    if d.pickup_start >= d.pickup_end:
        return "invalid pickup window"
    if d.pickup_start >= d.expires_at:
        return "pickup window starts after the food expires"
    return None


# ---------------------------------------------------------------------------
# Step 2: feasibility filter for a donor -> NGO pair
# ---------------------------------------------------------------------------
def volunteer_can_serve(d: DonationInput, volunteers: Iterable[VolunteerInput]) -> bool:
    for v in volunteers:
        if not v.is_available or v.vehicle_capacity_kg < d.quantity_kg:
            continue
        try:
            if haversine_km(v.latitude, v.longitude, d.latitude, d.longitude) <= v.max_distance_km:
                return True
        except ValueError:
            continue
    return False


def pair_infeasibility(
    d: DonationInput,
    n: NGOInput,
    max_distance_km: float,
) -> tuple[Optional[str], float]:
    """Check hard constraints. Returns (reason or None, distance_km)."""
    if not n.active:
        return "NGO account inactive", math.nan
    if d.category not in set(n.categories):
        return "does not accept this food category", math.nan
    if not _finite(n.capacity_kg) or n.capacity_kg <= 0:
        return "no available capacity", math.nan
    if n.capacity_kg < d.quantity_kg:
        return "available capacity is smaller than the donation", math.nan
    if not _finite(n.demand_kg) or n.demand_kg <= 0:
        return "no unmet demand", math.nan
    try:
        dist = haversine_km(d.latitude, d.longitude, n.latitude, n.longitude)
    except ValueError:
        return "invalid NGO coordinates", math.nan
    if dist > max_distance_km:
        return f"outside the {max_distance_km:g} km service radius", dist
    return None, dist


# ---------------------------------------------------------------------------
# Step 3-6: score, rank, explain
# ---------------------------------------------------------------------------
def score_pair(d: DonationInput, n: NGOInput, distance_km: float, now: datetime) -> Candidate:
    f = freshness_urgency(remaining_hours(d, now))
    g = geographic_proximity(distance_km)
    c = capacity_fit(d.quantity_kg, n.capacity_kg)
    q = demand_fit(d.quantity_kg, n.demand_kg)
    p = recipient_priority(n.priority)
    return Candidate(
        ngo_id=n.id,
        ngo_name=n.name,
        distance_km=round(distance_km, 3),
        freshness=f,
        proximity=g,
        capacity_fit=c,
        demand_fit=q,
        priority=p,
        score=weighted_score(f, g, c, q, p),
    )


def explain(c: Candidate, d: DonationInput, n: NGOInput, hours_left: float) -> str:
    """Plain-language justification built only from the computed components."""
    parts: list[str] = []
    if c.distance_km <= 2:
        parts.append(f"it is very close ({c.distance_km:.1f} km away)")
    elif c.distance_km <= 6:
        parts.append(f"it is nearby ({c.distance_km:.1f} km away)")
    else:
        parts.append(f"it is {c.distance_km:.1f} km away")
    parts.append("accepts this food category")
    if c.capacity_fit >= 0.5:
        parts.append(f"has capacity that closely fits the donation ({n.capacity_kg:.1f} kg available)")
    else:
        parts.append(f"has sufficient capacity ({n.capacity_kg:.1f} kg available)")
    if n.demand_kg >= d.quantity_kg:
        parts.append(f"has unmet demand ({n.demand_kg:.1f} kg) that covers the full quantity")
    else:
        parts.append(f"has relevant unmet demand ({n.demand_kg:.1f} kg)")
    if c.priority >= 0.7:
        parts.append("serves a high-priority population")
    text = f"{n.name} was recommended because " + ", ".join(parts[:-1]) + ", and " + parts[-1] + "."
    if hours_left <= 6:
        text += f" The food has only {hours_left:.1f} h of usable life left, so it is treated as urgent."
    # Which weighted component contributed most?
    contrib = {k: WEIGHTS[k] * v for k, v in c.components().items()}
    top = max(contrib, key=contrib.get)
    label = {
        "freshness": "freshness urgency",
        "proximity": "geographic proximity",
        "capacity_fit": "capacity fit",
        "demand_fit": "demand fit",
        "priority": "recipient priority",
    }[top]
    text += f" Largest score contribution: {label} ({contrib[top]:.3f} of {c.score:.3f})."
    return text


def rank_candidates(
    d: DonationInput,
    ngos: Iterable[NGOInput],
    now: datetime,
    *,
    max_distance_km: float = 25.0,
    limit: Optional[int] = 5,
    volunteers: Optional[Sequence[VolunteerInput]] = None,
    exclude_ngo_ids: Iterable[int] = (),
) -> MatchResult:
    """Run the full matching pipeline for one donation.

    1. validate the donation, 2. filter infeasible NGOs, 3. compute the five
    components, 4. compute S_ij, 5. rank by score (ties: shorter distance, then
    NGO id for determinism), 6. attach explanations.
    If `volunteers` is given, the donation additionally needs at least one
    available volunteer able to reach it (volunteer feasibility).
    """
    reason = validate_donation(d, now)
    if reason:
        return MatchResult(donation_id=d.id, valid=False, reason=reason)
    if volunteers is not None and not volunteer_can_serve(d, volunteers):
        return MatchResult(donation_id=d.id, valid=False, reason="no available volunteer can serve this pickup")

    excluded = set(exclude_ngo_ids)
    hours_left = remaining_hours(d, now)
    result = MatchResult(donation_id=d.id, valid=True)
    for n in ngos:
        if n.id in excluded:
            result.rejected[n.id] = "previously declined this donation"
            continue
        why, dist = pair_infeasibility(d, n, max_distance_km)
        if why:
            result.rejected[n.id] = why
            continue
        cand = score_pair(d, n, dist, now)
        cand.explanation = explain(cand, d, n, hours_left)
        result.candidates.append(cand)

    result.candidates.sort(key=lambda c: (-c.score, c.distance_km, c.ngo_id))
    if limit is not None:
        result.candidates = result.candidates[:limit]
    for i, c in enumerate(result.candidates, start=1):
        c.rank = i
    if not result.candidates:
        result.reason = "no feasible NGO found"
    return result
