"""Unit tests for the pure matching engine (backend/app/matching.py)."""
from __future__ import annotations

import math
from datetime import datetime, timedelta

import pytest

from app import matching as m

NOW = datetime(2026, 1, 1, 12, 0, 0)


def donation(**kw) -> m.DonationInput:
    base = dict(id=1, category="prepared_meals", quantity_kg=20.0, latitude=28.46, longitude=77.51,
                expires_at=NOW + timedelta(hours=5), pickup_start=NOW, pickup_end=NOW + timedelta(hours=3))
    base.update(kw)
    return m.DonationInput(**base)


def ngo(id=1, **kw) -> m.NGOInput:
    base = dict(id=id, name=f"NGO {id}", latitude=28.47, longitude=77.51, capacity_kg=50.0, demand_kg=30.0,
                priority=0.5, categories=["prepared_meals", "bakery"])
    base.update(kw)
    return m.NGOInput(**base)


# ---- weights --------------------------------------------------------------
def test_weights_match_report_and_sum_to_one():
    assert m.WEIGHTS == {"freshness": 0.0714, "proximity": 0.7280, "capacity_fit": 0.0654,
                         "demand_fit": 0.0464, "priority": 0.0888}
    assert sum(m.WEIGHTS.values()) == pytest.approx(1.0, abs=1e-9)


# ---- freshness F_i ---------------------------------------------------------
@pytest.mark.parametrize("hours,expected", [(0, 1.0), (6, 0.75), (12, 0.5), (24, 0.0), (48, 0.0)])
def test_freshness(hours, expected):
    assert m.freshness_urgency(hours) == pytest.approx(expected)


def test_freshness_invalid_inputs_are_safe():
    assert m.freshness_urgency(-3) == 1.0
    assert m.freshness_urgency(float("nan")) == 1.0
    assert m.freshness_urgency(None) == 1.0


# ---- proximity G_ij --------------------------------------------------------
def test_proximity():
    assert m.geographic_proximity(0) == pytest.approx(1.0)
    assert m.geographic_proximity(5) == pytest.approx(math.exp(-1))
    assert m.geographic_proximity(10) == pytest.approx(math.exp(-2))
    assert m.geographic_proximity(-1) == 0.0
    assert m.geographic_proximity(float("inf")) == 0.0


def test_haversine_known_distance():
    # Delhi (28.6139, 77.2090) to Agra (27.1767, 78.0081) is ~178 km great-circle.
    assert m.haversine_km(28.6139, 77.2090, 27.1767, 78.0081) == pytest.approx(178, abs=3)
    assert m.haversine_km(10, 10, 10, 10) == 0.0
    with pytest.raises(ValueError):
        m.haversine_km(95, 0, 0, 0)


# ---- capacity C_ij and demand Q_ij -----------------------------------------
@pytest.mark.parametrize("q,c,expected", [(20, 40, 0.5), (40, 20, 0.5), (30, 30, 1.0), (10, 100, 0.1)])
def test_ratio_fit(q, c, expected):
    assert m.capacity_fit(q, c) == pytest.approx(expected)
    assert m.demand_fit(q, c) == pytest.approx(expected)


@pytest.mark.parametrize("a,b", [(0, 10), (10, 0), (0, 0), (-5, 10), (float("nan"), 3)])
def test_ratio_fit_zero_and_invalid_never_divides_by_zero(a, b):
    assert m.ratio_fit(a, b) == 0.0


def test_priority_clamped():
    assert m.recipient_priority(0.4) == 0.4
    assert m.recipient_priority(2) == 1.0
    assert m.recipient_priority(-1) == 0.0
    assert m.recipient_priority(float("nan")) == 0.0


# ---- final score -----------------------------------------------------------
def test_weighted_score_formula():
    f, g, c, q, p = 0.75, 0.6, 0.5, 0.4, 0.9
    expected = 0.0714 * f + 0.7280 * g + 0.0654 * c + 0.0464 * q + 0.0888 * p
    assert m.weighted_score(f, g, c, q, p) == pytest.approx(expected)
    assert m.weighted_score(1, 1, 1, 1, 1) == pytest.approx(1.0)
    assert m.weighted_score(0, 0, 0, 0, 0) == 0.0


def test_score_pair_matches_components():
    d = donation()
    n = ngo()
    dist = m.haversine_km(d.latitude, d.longitude, n.latitude, n.longitude)
    c = m.score_pair(d, n, dist, NOW)
    assert c.freshness == pytest.approx(1 - 5 / 24)
    assert c.proximity == pytest.approx(math.exp(-dist / 5))
    assert c.capacity_fit == pytest.approx(20 / 50)
    assert c.demand_fit == pytest.approx(20 / 30)
    assert c.priority == 0.5
    assert c.score == pytest.approx(m.weighted_score(c.freshness, c.proximity, c.capacity_fit, c.demand_fit, c.priority))


# ---- feasibility -----------------------------------------------------------
def test_category_filter():
    res = m.rank_candidates(donation(category="dairy"), [ngo()], NOW)
    assert res.candidates == [] and "category" in res.rejected[1]


def test_capacity_filter_zero_and_insufficient():
    res = m.rank_candidates(donation(), [ngo(1, capacity_kg=0), ngo(2, capacity_kg=10)], NOW)
    assert res.candidates == []
    assert res.rejected[1] == "no available capacity"
    assert "smaller" in res.rejected[2]


def test_demand_filter():
    res = m.rank_candidates(donation(), [ngo(demand_kg=0)], NOW)
    assert res.candidates == [] and res.rejected[1] == "no unmet demand"


def test_radius_and_invalid_coordinates_filter():
    far = ngo(1, latitude=29.5)  # >100 km away
    bad = ngo(2, latitude=float("nan"))
    res = m.rank_candidates(donation(), [far, bad], NOW, max_distance_km=25)
    assert res.candidates == []
    assert "radius" in res.rejected[1]
    assert "coordinates" in res.rejected[2]


def test_inactive_and_excluded_ngos_filtered():
    res = m.rank_candidates(donation(), [ngo(1, active=False), ngo(2)], NOW, exclude_ngo_ids=[2])
    assert res.candidates == []


@pytest.mark.parametrize("kw,reason", [
    ({"expires_at": NOW - timedelta(minutes=1)}, "expired"),
    ({"pickup_end": NOW - timedelta(minutes=1)}, "closed"),
    ({"status": "accepted"}, "accepted"),
    ({"quantity_kg": 0}, "quantity"),
    ({"latitude": 123.0}, "coordinates"),
    ({"pickup_start": NOW + timedelta(hours=6), "pickup_end": NOW + timedelta(hours=7)}, "after the food expires"),
])
def test_invalid_donations_rejected(kw, reason):
    res = m.rank_candidates(donation(**kw), [ngo()], NOW)
    assert not res.valid and reason in res.reason


def test_volunteer_feasibility():
    d = donation()
    far_vol = m.VolunteerInput(1, 29.5, 77.51, True, 100, 10)
    small_vol = m.VolunteerInput(2, 28.46, 77.51, True, 5, 10)
    off_vol = m.VolunteerInput(3, 28.46, 77.51, False, 100, 10)
    assert not m.rank_candidates(d, [ngo()], NOW, volunteers=[far_vol, small_vol, off_vol]).valid
    good = m.VolunteerInput(4, 28.461, 77.51, True, 100, 10)
    assert m.rank_candidates(d, [ngo()], NOW, volunteers=[good]).candidates


# ---- ranking ---------------------------------------------------------------
def test_ranking_prefers_nearby_and_is_sorted():
    near = ngo(1, latitude=28.462)
    mid = ngo(2, latitude=28.50)
    far = ngo(3, latitude=28.58)
    res = m.rank_candidates(donation(), [far, near, mid], NOW, limit=None)
    assert [c.ngo_id for c in res.candidates] == [1, 2, 3]
    assert [c.rank for c in res.candidates] == [1, 2, 3]
    scores = [c.score for c in res.candidates]
    assert scores == sorted(scores, reverse=True)


def test_priority_breaks_ties_at_equal_distance():
    low = ngo(1, priority=0.2)
    high = ngo(2, priority=0.9)
    res = m.rank_candidates(donation(), [low, high], NOW)
    assert res.candidates[0].ngo_id == 2


def test_limit_and_explanations():
    ngos = [ngo(i, latitude=28.46 + i * 0.005) for i in range(1, 9)]
    res = m.rank_candidates(donation(expires_at=NOW + timedelta(hours=3)), ngos, NOW, limit=5)
    assert len(res.candidates) == 5
    for c in res.candidates:
        assert c.explanation.startswith(c.ngo_name + " was recommended because")
        assert "accepts this food category" in c.explanation
        assert "urgent" in c.explanation  # 3 h left
