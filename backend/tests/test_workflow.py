"""End-to-end lifecycle: accept, duplicate prevention, volunteer tasks, state transitions."""
from __future__ import annotations

import threading

from sqlalchemy import select

from app.database import SessionLocal
from app.models import AuditLog

from .conftest import BASE_LAT, donation_payload, login, make_admin, register


def _post(client, donor, **kw):
    r = client.post("/api/donations", json=donation_payload(**kw), headers=donor["headers"])
    assert r.status_code == 201, r.text
    return r.json()


def _recs(client, donor, donation_id):
    return client.get(f"/api/matches/donation/{donation_id}", headers=donor["headers"]).json()


def test_full_lifecycle_posted_to_delivered(client, db):
    donor = register(client, "donor")
    ngo = register(client, "ngo")
    vol = register(client, "volunteer")
    d = _post(client, donor)
    rec = _recs(client, donor, d["id"])[0]

    # NGO sees the offer and accepts it
    offers = client.get("/api/ngo/recommendations", headers=ngo["headers"]).json()
    assert offers and offers[0]["donation"]["id"] == d["id"]
    r = client.post(f"/api/matches/{rec['id']}/accept", headers=ngo["headers"])
    assert r.status_code == 200 and r.json()["status"] == "accepted"
    assert client.get(f"/api/donations/{d['id']}", headers=donor["headers"]).json()["status"] == "accepted"

    # Volunteer sees an eligible open task without contact details, then accepts
    tasks = client.get("/api/volunteer/tasks/available", headers=vol["headers"]).json()
    assert len(tasks) == 1 and tasks[0]["eligible"] is True and tasks[0]["donor_phone"] is None
    tid = tasks[0]["id"]
    t = client.post(f"/api/volunteer/tasks/{tid}/accept", headers=vol["headers"]).json()
    assert t["status"] == "accepted" and t["accepted_at"] and t["donor_name"]

    # Cannot deliver before pickup
    assert client.post(f"/api/volunteer/tasks/{tid}/status", json={"status": "delivered"}, headers=vol["headers"]).status_code == 409
    t = client.post(f"/api/volunteer/tasks/{tid}/status", json={"status": "picked_up"}, headers=vol["headers"]).json()
    assert t["status"] == "picked_up" and t["picked_up_at"]
    assert client.get(f"/api/donations/{d['id']}", headers=donor["headers"]).json()["status"] == "picked_up"
    t = client.post(f"/api/volunteer/tasks/{tid}/status", json={"status": "delivered"}, headers=vol["headers"]).json()
    assert t["status"] == "delivered" and t["delivered_at"]
    final = client.get(f"/api/donations/{d['id']}", headers=donor["headers"]).json()
    assert final["status"] == "delivered"

    # Delivered is terminal: cannot cancel, cannot redeliver
    assert client.post(f"/api/donations/{d['id']}/cancel", headers=donor["headers"]).status_code == 409
    assert client.post(f"/api/volunteer/tasks/{tid}/status", json={"status": "delivered"}, headers=vol["headers"]).status_code == 409

    # Notifications were created for each participant
    kinds = {n["kind"] for n in client.get("/api/notifications", headers=donor["headers"]).json()["items"]}
    assert {"match_ready", "ngo_accepted", "volunteer_accepted", "task_picked_up", "task_delivered"} <= kinds
    assert any(n["kind"] == "new_offer" for n in client.get("/api/notifications", headers=ngo["headers"]).json()["items"])
    assert any(n["kind"] == "new_task" for n in client.get("/api/notifications", headers=vol["headers"]).json()["items"])

    # Audit trail
    actions = set(db.scalars(select(AuditLog.action)).all())
    assert {"donation_created", "matching_run", "match_accepted", "task_accepted", "task_picked_up", "task_delivered"} <= actions

    # Stats reflect the delivery
    stats = client.get("/api/ngo/stats", headers=ngo["headers"]).json()
    assert stats["delivered"] == 1 and stats["kg_received"] == 20
    email, pw = make_admin(db)
    admin_stats = client.get("/api/admin/stats", headers=login(client, email, pw)).json()
    assert admin_stats["kg_delivered"] == 20 and admin_stats["completed_deliveries"] == 1


def test_duplicate_acceptance_prevented(client):
    donor = register(client, "donor")
    ngo_a = register(client, "ngo")
    ngo_b = register(client, "ngo", ngo={"latitude": BASE_LAT + 0.02})
    d = _post(client, donor)
    recs = {r["ngo_id"]: r for r in _recs(client, donor, d["id"])}
    assert len(recs) == 2
    a_id = ngo_a["me"]["ngo"]["id"]
    b_id = ngo_b["me"]["ngo"]["id"]
    assert client.post(f"/api/matches/{recs[a_id]['id']}/accept", headers=ngo_a["headers"]).status_code == 200
    # Same NGO again, and the other NGO, are both rejected
    assert client.post(f"/api/matches/{recs[a_id]['id']}/accept", headers=ngo_a["headers"]).status_code == 409
    assert client.post(f"/api/matches/{recs[b_id]['id']}/accept", headers=ngo_b["headers"]).status_code == 409
    # Capacity was reserved exactly once
    assert client.get("/api/ngo/profile", headers=ngo_a["headers"]).json()["capacity_kg"] == 80
    assert client.get("/api/ngo/profile", headers=ngo_b["headers"]).json()["capacity_kg"] == 100


def test_concurrent_acceptance_only_one_wins(client):
    donor = register(client, "donor")
    ngos = [register(client, "ngo", ngo={"latitude": BASE_LAT + 0.005 * (i + 1)}) for i in range(3)]
    d = _post(client, donor)
    recs = {r["ngo_id"]: r for r in _recs(client, donor, d["id"])}
    results = []
    barrier = threading.Barrier(len(ngos))

    def accept(n):
        barrier.wait()
        rid = recs[n["me"]["ngo"]["id"]]["id"]
        results.append(client.post(f"/api/matches/{rid}/accept", headers=n["headers"]).status_code)

    threads = [threading.Thread(target=accept, args=(n,)) for n in ngos]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results).count(200) == 1, results
    total_capacity = sum(client.get("/api/ngo/profile", headers=n["headers"]).json()["capacity_kg"] for n in ngos)
    assert total_capacity == 300 - 20


def test_ngo_cannot_accept_other_ngos_match_or_violate_constraints(client):
    donor = register(client, "donor")
    ngo_a = register(client, "ngo")
    ngo_b = register(client, "ngo", ngo={"latitude": BASE_LAT + 0.02})
    d = _post(client, donor)
    recs = {r["ngo_id"]: r for r in _recs(client, donor, d["id"])}
    a_rec = recs[ngo_a["me"]["ngo"]["id"]]
    assert client.post(f"/api/matches/{a_rec['id']}/accept", headers=ngo_b["headers"]).status_code == 403

    # NGO A shrinks capacity below the donation: matching refresh removes it, acceptance would fail
    client.patch("/api/ngo/profile", json={"capacity_kg": 5}, headers=ngo_a["headers"])
    assert client.post(f"/api/matches/{a_rec['id']}/accept", headers=ngo_a["headers"]).status_code == 409
    current = {r["ngo_id"] for r in _recs(client, donor, d["id"])}
    assert ngo_a["me"]["ngo"]["id"] not in current

    # NGO B drops the category: no longer recommended
    client.patch("/api/ngo/profile", json={"accepted_categories": ["dairy"]}, headers=ngo_b["headers"])
    assert client.get(f"/api/donations/{d['id']}", headers=donor["headers"]).json()["status"] == "posted"


def test_reject_rematches_without_declining_ngo(client):
    donor = register(client, "donor")
    ngo_a = register(client, "ngo")
    d = _post(client, donor)
    rec = _recs(client, donor, d["id"])[0]
    r = client.post(f"/api/matches/{rec['id']}/reject", json={"reason": "No cold storage today"}, headers=ngo_a["headers"])
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    assert client.get(f"/api/donations/{d['id']}", headers=donor["headers"]).json()["status"] == "posted"
    # A new NGO registers and gets the offer; the declining NGO is never re-proposed
    ngo_b = register(client, "ngo", ngo={"latitude": BASE_LAT + 0.03})
    current = _recs(client, donor, d["id"])
    assert [r["ngo_id"] for r in current] == [ngo_b["me"]["ngo"]["id"]]
    client.patch("/api/ngo/profile", json={"demand_kg": 90}, headers=ngo_a["headers"])
    assert ngo_a["me"]["ngo"]["id"] not in {r["ngo_id"] for r in _recs(client, donor, d["id"])}


def test_volunteer_eligibility_and_ownership(client):
    donor = register(client, "donor")
    ngo = register(client, "ngo")
    small = register(client, "volunteer", volunteer={"vehicle_capacity_kg": 5})
    far = register(client, "volunteer", volunteer={"latitude": BASE_LAT + 1.0})
    good = register(client, "volunteer")
    other = register(client, "volunteer")
    d = _post(client, donor)
    rec = _recs(client, donor, d["id"])[0]
    client.post(f"/api/matches/{rec['id']}/accept", headers=ngo["headers"])
    tid = client.get("/api/volunteer/tasks/available", headers=good["headers"]).json()[0]["id"]

    small_view = client.get("/api/volunteer/tasks/available", headers=small["headers"]).json()[0]
    assert small_view["eligible"] is False and "capacity" in small_view["ineligible_reason"]
    assert client.post(f"/api/volunteer/tasks/{tid}/accept", headers=small["headers"]).status_code == 409
    assert client.post(f"/api/volunteer/tasks/{tid}/accept", headers=far["headers"]).status_code == 409

    # Unavailable volunteers cannot accept
    client.patch("/api/volunteer/profile", json={"is_available": False}, headers=other["headers"])
    assert client.post(f"/api/volunteer/tasks/{tid}/accept", headers=other["headers"]).status_code == 409

    assert client.post(f"/api/volunteer/tasks/{tid}/accept", headers=good["headers"]).status_code == 200
    client.patch("/api/volunteer/profile", json={"is_available": True}, headers=other["headers"])
    assert client.post(f"/api/volunteer/tasks/{tid}/accept", headers=other["headers"]).status_code == 409
    # Only the assigned volunteer can update; donors/NGOs cannot mark it delivered
    assert client.post(f"/api/volunteer/tasks/{tid}/status", json={"status": "picked_up"}, headers=other["headers"]).status_code == 403
    assert client.post(f"/api/volunteer/tasks/{tid}/status", json={"status": "picked_up"}, headers=donor["headers"]).status_code == 403
    assert client.post(f"/api/volunteer/tasks/{tid}/status", json={"status": "picked_up"}, headers=good["headers"]).status_code == 200


def test_reports_and_admin_resolution(client, db):
    donor = register(client, "donor")
    ngo = register(client, "ngo")
    d = _post(client, donor)
    r = client.post("/api/reports", json={"entity_type": "donation", "entity_id": d["id"], "reason": "Packaging looked damaged"},
                    headers=ngo["headers"])
    assert r.status_code == 201
    assert client.post("/api/reports", json={"entity_type": "donation", "entity_id": d["id"], "reason": "Duplicate report"},
                       headers=ngo["headers"]).status_code == 409
    email, pw = make_admin(db)
    admin = login(client, email, pw)
    open_reports = client.get("/api/admin/reports", headers=admin).json()
    assert len(open_reports) == 1
    res = client.post(f"/api/admin/reports/{open_reports[0]['id']}/resolve",
                      json={"status": "resolved", "cancel_donation": True, "resolution_note": "Cancelled"}, headers=admin)
    assert res.status_code == 200
    assert client.get(f"/api/donations/{d['id']}", headers=donor["headers"]).json()["status"] == "cancelled"
    assert client.get("/api/admin/audit?action=report_resolved", headers=admin).json()["total"] == 1


def test_nonexistent_resources_return_404(client):
    ngo = register(client, "ngo")
    assert client.post("/api/matches/9999/accept", headers=ngo["headers"]).status_code == 404
    assert client.get("/api/donations/9999", headers=ngo["headers"]).status_code == 404


def test_meta_and_weights_public(client):
    meta = client.get("/api/meta").json()
    assert [c["key"] for c in meta["categories"]] == ["prepared_meals", "bakery", "fruits_vegetables", "dairy", "packaged"]
    w = client.get("/api/matches/weights").json()
    assert w["weights"]["proximity"] == 0.728 and abs(w["sum"] - 1) < 1e-9
    # Static frontend served from the same origin with security headers
    page = client.get("/")
    assert page.status_code == 200 and "FoodRescue AI" in page.text
    assert page.headers["x-frame-options"] == "DENY"
    assert "default-src 'self'" in page.headers["content-security-policy"]
