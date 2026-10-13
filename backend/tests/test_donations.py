"""Donation creation, validation, automatic matching, expiry and cancellation."""
from __future__ import annotations

from datetime import timedelta

from app.database import SessionLocal
from app.models import Donation, NGOProfile
from app.services import run_maintenance

from .conftest import donation_payload, iso, now_utc, register


def test_create_donation_runs_matching(client):
    donor = register(client, "donor")
    register(client, "ngo")
    r = client.post("/api/donations", json=donation_payload(), headers=donor["headers"])
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["status"] == "matched"
    assert 4.9 < d["remaining_hours"] <= 5
    recs = client.get(f"/api/matches/donation/{d['id']}", headers=donor["headers"]).json()
    assert len(recs) == 1
    rec = recs[0]
    for key in ("freshness", "proximity", "capacity_fit", "demand_fit", "priority", "score", "explanation"):
        assert key in rec
    assert rec["rank"] == 1 and rec["status"] == "proposed"


def test_donation_without_feasible_ngo_stays_posted(client):
    donor = register(client, "donor")
    register(client, "ngo", ngo={"accepted_categories": ["dairy"]})
    d = client.post("/api/donations", json=donation_payload(), headers=donor["headers"]).json()
    assert d["status"] == "posted"


def test_validation_errors(client):
    donor = register(client, "donor")
    h = donor["headers"]
    assert client.post("/api/donations", json={}, headers=h).status_code == 422
    assert client.post("/api/donations", json=donation_payload(category="meat"), headers=h).status_code == 422
    assert client.post("/api/donations", json=donation_payload(quantity=0), headers=h).status_code == 422
    assert client.post("/api/donations", json=donation_payload(quantity=-2), headers=h).status_code == 422
    assert client.post("/api/donations", json=donation_payload(latitude=200), headers=h).status_code == 422
    assert client.post("/api/donations", json=donation_payload(usable_life_hours=0), headers=h).status_code == 422
    # Portions need an estimated weight
    r = client.post("/api/donations", json=donation_payload(unit="portions", quantity=50), headers=h)
    assert r.status_code == 422 and "quantity_kg" in r.text
    assert client.post("/api/donations", json=donation_payload(unit="portions", quantity=50, quantity_kg=15),
                       headers=h).status_code == 201
    # Pickup window must end after it starts and in the future
    now = now_utc()
    bad_window = donation_payload(pickup_start=iso(now + timedelta(hours=2)), pickup_end=iso(now + timedelta(hours=1)))
    assert client.post("/api/donations", json=bad_window, headers=h).status_code == 422
    past = donation_payload(pickup_start=iso(now - timedelta(hours=3)), pickup_end=iso(now - timedelta(hours=1)))
    assert client.post("/api/donations", json=past, headers=h).status_code == 422
    after_expiry = donation_payload(usable_life_hours=1, pickup_start=iso(now + timedelta(hours=2)),
                                    pickup_end=iso(now + timedelta(hours=3)))
    assert client.post("/api/donations", json=after_expiry, headers=h).status_code == 422


def test_donor_only_sees_own_donations(client):
    a = register(client, "donor")
    b = register(client, "donor")
    d = client.post("/api/donations", json=donation_payload(), headers=a["headers"]).json()
    assert client.get(f"/api/donations/{d['id']}", headers=b["headers"]).status_code == 404
    assert client.post(f"/api/donations/{d['id']}/cancel", headers=b["headers"]).status_code == 404
    assert client.get("/api/donations", headers=b["headers"]).json()["total"] == 0


def test_expired_donation_handling(client):
    donor = register(client, "donor")
    ngo = register(client, "ngo")
    d = client.post("/api/donations", json=donation_payload(usable_life_hours=1), headers=donor["headers"]).json()
    with SessionLocal() as db:
        stats = run_maintenance(db, now=now_utc() + timedelta(hours=2))
    assert stats["expired"] == 1
    got = client.get(f"/api/donations/{d['id']}", headers=donor["headers"]).json()
    assert got["status"] == "expired"
    # The NGO can no longer accept it
    recs = client.get(f"/api/matches/donation/{d['id']}?include_history=true", headers=donor["headers"]).json()
    assert all(r["status"] != "proposed" for r in recs)
    assert client.get("/api/ngo/recommendations", headers=ngo["headers"]).json() == []
    notes = client.get("/api/notifications", headers=donor["headers"]).json()["items"]
    assert any(n["kind"] == "expired" for n in notes)


def test_expiry_warning_sent_once(client):
    donor = register(client, "donor")
    register(client, "ngo")
    client.post("/api/donations", json=donation_payload(usable_life_hours=1.5), headers=donor["headers"])
    with SessionLocal() as db:
        assert run_maintenance(db)["warned"] == 1
        assert run_maintenance(db)["warned"] == 0


def test_cancel_accepted_donation_releases_capacity(client):
    donor = register(client, "donor")
    ngo = register(client, "ngo")
    d = client.post("/api/donations", json=donation_payload(quantity=20), headers=donor["headers"]).json()
    rec = client.get(f"/api/matches/donation/{d['id']}", headers=donor["headers"]).json()[0]
    assert client.post(f"/api/matches/{rec['id']}/accept", headers=ngo["headers"]).status_code == 200
    prof = client.get("/api/ngo/profile", headers=ngo["headers"]).json()
    assert prof["capacity_kg"] == 80 and prof["demand_kg"] == 60
    r = client.post(f"/api/donations/{d['id']}/cancel", headers=donor["headers"])
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    prof = client.get("/api/ngo/profile", headers=ngo["headers"]).json()
    assert prof["capacity_kg"] == 100 and prof["demand_kg"] == 80
    # Cancelling twice is an invalid transition
    assert client.post(f"/api/donations/{d['id']}/cancel", headers=donor["headers"]).status_code == 409


def test_persistence_across_sessions(client):
    donor = register(client, "donor")
    d = client.post("/api/donations", json=donation_payload(food_name="Persisted bread", category="bakery"),
                    headers=donor["headers"]).json()
    with SessionLocal() as db:
        row = db.get(Donation, d["id"])
        assert row.food_name == "Persisted bread"
        assert row.quantity_kg == 20
        assert db.query(NGOProfile).count() == 0


def test_image_upload_validation(client):
    donor = register(client, "donor")
    d = client.post("/api/donations", json=donation_payload(), headers=donor["headers"]).json()
    bad = client.post(f"/api/donations/{d['id']}/image", files={"file": ("x.png", b"not an image", "image/png")},
                      headers=donor["headers"])
    assert bad.status_code == 415
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    ok = client.post(f"/api/donations/{d['id']}/image", files={"file": ("x.png", png, "image/png")}, headers=donor["headers"])
    assert ok.status_code == 200 and ok.json()["image_url"].startswith("/uploads/")
