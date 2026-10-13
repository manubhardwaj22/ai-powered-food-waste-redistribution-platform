"""Shared pytest fixtures. Uses a throwaway SQLite database per test session."""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="foodrescue-test-"))
os.environ["DATABASE_URL"] = f"sqlite:///{(_TMP / 'test.db').as_posix()}"
os.environ["UPLOAD_DIR"] = str(_TMP / "uploads")
os.environ["SECRET_KEY"] = "test-secret-key-for-pytest-only-0123456789abcdef"
os.environ["MAINTENANCE_INTERVAL_SECONDS"] = "0"
os.environ["APP_ENV"] = "development"

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402

# Coordinates near Greater Noida used throughout the tests.
BASE_LAT, BASE_LON = 28.4600, 77.5100


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


def iso(dt: datetime) -> str:
    return dt.replace(tzinfo=timezone.utc).isoformat()


def now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


_counter = {"n": 0}


def register(client, role: str, **extra) -> dict:
    """Register a user and return {'headers', 'user', 'me'}."""
    _counter["n"] += 1
    n = _counter["n"]
    body = {
        "email": f"{role}{n}@test.example",
        "password": "Passw0rd!",
        "full_name": f"Test {role.title()} {n}",
        "role": role,
    }
    if role == "ngo":
        ngo = {
            "org_name": f"Test NGO {n}",
            "address": "Test address",
            "latitude": BASE_LAT + 0.01,
            "longitude": BASE_LON,
            "priority": 0.7,
            "capacity_kg": 100,
            "demand_kg": 80,
            "accepted_categories": ["prepared_meals", "bakery"],
        }
        ngo.update(extra.pop("ngo", {}))
        body["ngo"] = ngo
    if role == "volunteer":
        vol = {"latitude": BASE_LAT, "longitude": BASE_LON, "vehicle_capacity_kg": 50, "max_distance_km": 10}
        vol.update(extra.pop("volunteer", {}))
        body["volunteer"] = vol
    body.update(extra)
    r = client.post("/api/auth/register", json=body)
    assert r.status_code == 201, r.text
    data = r.json()
    headers = {"Authorization": f"Bearer {data['access_token']}"}
    me = client.get("/api/auth/me", headers=headers).json()
    return {"headers": headers, "user": data["user"], "me": me, "email": body["email"]}


def donation_payload(**overrides) -> dict:
    now = now_utc()
    body = {
        "food_name": "Veg biryani",
        "category": "prepared_meals",
        "quantity": 20,
        "unit": "kg",
        "usable_life_hours": 5,
        "pickup_address": "Test kitchen",
        "latitude": BASE_LAT,
        "longitude": BASE_LON,
        "pickup_start": iso(now),
        "pickup_end": iso(now + timedelta(hours=3)),
    }
    body.update(overrides)
    return body


def make_admin(db, email="admin@test.example", password="Adm1nPass!"):
    from app.auth import hash_password
    from app.models import User

    u = User(email=email, full_name="Test Admin", role="admin", password_hash=hash_password(password))
    db.add(u)
    db.commit()
    return email, password


def login(client, email, password) -> dict:
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}
