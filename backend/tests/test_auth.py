"""Registration, authentication and role-based access control."""
from __future__ import annotations

from sqlalchemy import select

from app.models import User

from .conftest import login, make_admin, register


def test_register_and_login_roundtrip(client):
    a = register(client, "donor")
    assert a["user"]["role"] == "donor"
    headers = login(client, a["email"], "Passw0rd!")
    me = client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["user"]["email"] == a["email"]


def test_password_is_hashed_not_plaintext(client, db):
    a = register(client, "donor")
    u = db.scalar(select(User).where(User.email == a["email"]))
    assert u.password_hash != "Passw0rd!"
    assert u.password_hash.startswith("$2")  # bcrypt


def test_duplicate_email_rejected(client):
    a = register(client, "donor")
    r = client.post("/api/auth/register", json={"email": a["email"], "password": "Passw0rd!", "full_name": "X Y", "role": "donor"})
    assert r.status_code == 409


def test_weak_password_and_missing_profiles_rejected(client):
    base = {"email": "w@test.example", "full_name": "Weak Pass"}
    assert client.post("/api/auth/register", json={**base, "password": "short", "role": "donor"}).status_code == 422
    assert client.post("/api/auth/register", json={**base, "password": "lettersonly", "role": "donor"}).status_code == 422
    assert client.post("/api/auth/register", json={**base, "password": "Passw0rd!", "role": "ngo"}).status_code == 422
    assert client.post("/api/auth/register", json={**base, "password": "Passw0rd!", "role": "volunteer"}).status_code == 422


def test_cannot_self_register_as_admin(client):
    r = client.post("/api/auth/register", json={"email": "evil@test.example", "password": "Passw0rd!", "full_name": "Evil", "role": "admin"})
    assert r.status_code == 422


def test_invalid_login(client):
    a = register(client, "donor")
    assert client.post("/api/auth/login", json={"email": a["email"], "password": "Wrong123"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "nobody@test.example", "password": "Passw0rd!"}).status_code == 401


def test_unauthenticated_and_bad_token(client):
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer not-a-token"}).status_code == 401
    assert client.get("/api/donations").status_code == 401


def test_role_permissions_enforced_server_side(client, db):
    donor = register(client, "donor")
    ngo = register(client, "ngo")
    vol = register(client, "volunteer")
    # Non-admins cannot reach admin endpoints
    for who in (donor, ngo, vol):
        assert client.get("/api/admin/stats", headers=who["headers"]).status_code == 403
    # Only donors create donations; only NGOs use NGO endpoints; only volunteers see tasks
    assert client.post("/api/donations", json={}, headers=ngo["headers"]).status_code == 403
    assert client.get("/api/ngo/recommendations", headers=donor["headers"]).status_code == 403
    assert client.get("/api/volunteer/tasks/available", headers=ngo["headers"]).status_code == 403
    # Admin can
    email, pw = make_admin(db)
    assert client.get("/api/admin/stats", headers=login(client, email, pw)).status_code == 200


def test_deactivated_user_blocked(client, db):
    donor = register(client, "donor")
    email, pw = make_admin(db)
    admin = login(client, email, pw)
    r = client.patch(f"/api/admin/users/{donor['user']['id']}/active", json={"is_active": False}, headers=admin)
    assert r.status_code == 200
    assert client.get("/api/auth/me", headers=donor["headers"]).status_code == 401
    assert client.post("/api/auth/login", json={"email": donor["email"], "password": "Passw0rd!"}).status_code == 403
