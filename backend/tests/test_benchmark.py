"""Synthetic benchmark: dataset calibration, reproducibility and metric definitions."""
from __future__ import annotations

import pytest

from app import benchmark as b


@pytest.fixture(scope="module")
def result():
    return b.run_benchmark()


def test_dataset_matches_report_characteristics():
    offers, ngos = b.generate_dataset(7)
    assert len(offers) == 900 and len(ngos) == 90
    assert set(offers.category) == set(b.CATEGORIES)
    assert offers.quantity_kg.sum() == pytest.approx(16915.6, abs=0.15)
    assert ngos.capacity_kg.sum() == pytest.approx(15191.2, abs=0.15)
    assert ngos.demand_kg.sum() == pytest.approx(12299.1, abs=0.15)
    assert (offers.quantity_kg > 0).all() and (ngos.capacity_kg > 0).all()
    assert all(len(c) >= 1 for c in ngos.categories)


def test_seed_reproducibility():
    o1, n1 = b.generate_dataset(7)
    o2, n2 = b.generate_dataset(7)
    o3, _ = b.generate_dataset(8)
    assert o1.equals(o2) and n1.equals(n2)
    assert not o1.quantity_kg.equals(o3.quantity_kg)
    assert b.run_benchmark(7)["methods"] == b.run_benchmark(7)["methods"]


def test_all_methods_evaluated_with_consistent_metrics(result):
    assert set(result["methods"]) == {"random", "nearest", "fifo", "proposed"}
    for m in result["methods"].values():
        assert 0 <= m["quantity_fulfillment_pct"] <= 100
        assert m["waste_ratio_pct"] == pytest.approx(100 - m["quantity_fulfillment_pct"], abs=0.011)
        assert 0 <= m["urgent_rescue_pct"] <= 100
        assert 0 <= m["full_match_pct"] <= 100
        assert 0 < m["avg_distance_km"] <= b.MAX_RADIUS_KM
        # Assigned quantity can never exceed total stated demand
        assert m["assigned_kg"] <= 12299.1 + 0.1


def test_proposed_method_behaviour(result):
    p = result["methods"]["proposed"]
    assert p["avg_distance_km"] < result["methods"]["random"]["avg_distance_km"]
    assert p["avg_distance_km"] <= result["methods"]["nearest"]["avg_distance_km"]
    assert p["urgent_rescue_pct"] > result["methods"]["random"]["urgent_rescue_pct"]


def test_reference_values_kept_separate(result):
    assert result["synthetic"] is True
    assert result["reported_proposed_reference"]["quantity_fulfillment_pct"] == 64.17
    calculated = {k: result["methods"]["proposed"][k] for k in result["reported_proposed_reference"]}
    assert calculated != result["reported_proposed_reference"]  # calculated independently, never copied


def test_evaluate_definitions_on_tiny_case():
    import pandas as pd

    offers = pd.DataFrame({"offer_id": [0, 1], "category": ["bakery", "bakery"], "quantity_kg": [10.0, 10.0],
                           "remaining_hours": [3.0, 30.0], "x": [0.0, 0.0], "y": [0.0, 0.0]})
    ngos = pd.DataFrame({"ngo_id": [0], "x": [3.0], "y": [4.0], "capacity_kg": [15.0], "demand_kg": [15.0],
                         "priority": [0.5], "categories": [["bakery"]]})
    st = b.State(offers, ngos)
    b.run_proposed(st, None)
    ev = b.evaluate(st)
    # Urgent offer (3 h) wins the NGO first and is fully served; the other gets the remaining 5 kg.
    assert st.assigned.tolist() == [10.0, 5.0]
    assert ev["quantity_fulfillment_pct"] == 75.0
    assert ev["full_match_pct"] == 50.0
    assert ev["urgent_rescue_pct"] == 100.0
    assert ev["avg_distance_km"] == 5.0
