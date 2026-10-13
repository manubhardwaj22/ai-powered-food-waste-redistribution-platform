"""Explicit demo-data seeding (`python run.py seed`).

Safety rules:
  * never deletes or updates existing records;
  * refuses to run if the database already contains any non-demo account;
  * does nothing if demo accounts already exist.

All organisations, people and donations created here are FICTIONAL and use
the reserved `.example` email domain. Locations are scattered around Greater
Noida, Uttar Pradesh, purely for a realistic-looking demo map.
"""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select

from . import config
from .auth import hash_password
from .database import SessionLocal, init_db, utcnow
from .models import Donation, MatchRecommendation, NGOProfile, User, VolunteerProfile
from .notifications import audit
from .services import accept_match, accept_task, generate_matches, update_task_status

DOMAIN = "foodrescue.example"

NGOS = [
    # name, lat, lon, priority, capacity, demand, categories
    ("Demo Community Kitchen Alpha", 28.4612, 77.5021, 0.9, 120, 90, ["prepared_meals", "bakery", "fruits_vegetables"]),
    ("Demo Food Bank Beta", 28.4744, 77.5163, 0.6, 300, 220, ["packaged", "fruits_vegetables", "dairy", "bakery"]),
    ("Demo Shelter Gamma", 28.4489, 77.5312, 0.8, 60, 45, ["prepared_meals", "dairy"]),
    ("Demo Children's Home Delta", 28.4931, 77.5368, 0.95, 50, 40, ["prepared_meals", "bakery", "dairy", "fruits_vegetables"]),
    ("Demo Relief Centre Epsilon", 28.4402, 77.5577, 0.5, 200, 150, ["packaged", "bakery", "prepared_meals"]),
    ("Demo Night Shelter Zeta", 28.5102, 77.5011, 0.7, 80, 60, ["prepared_meals", "packaged"]),
]

DONORS = [
    ("Demo Grand Hotel", "donor.hotel", 28.4675, 77.5134, "Hotel kitchen, service entrance"),
    ("Demo Corner Bakery", "donor.bakery", 28.4520, 77.5260, "Shop front, Alpha-1 market"),
    ("Demo Events & Catering", "donor.events", 28.4830, 77.5290, "Banquet hall loading bay"),
]

VOLUNTEERS = [
    ("Demo Volunteer Riya", "volunteer.riya", 28.4650, 77.5150, "bike", 25, 8),
    ("Demo Volunteer Arjun", "volunteer.arjun", 28.4800, 77.5250, "car", 120, 15),
    ("Demo Volunteer Meera", "volunteer.meera", 28.4500, 77.5400, "van", 400, 20),
]


def _user(db, email: str, name: str, role: str, org: str | None = None, phone: str | None = None) -> User:
    u = User(email=email, password_hash=hash_password(config.DEMO_PASSWORD), full_name=name, role=role,
             organization=org, phone=phone, is_demo=True)
    db.add(u)
    db.flush()
    return u


def seed() -> str:
    init_db()
    with SessionLocal() as db:
        real = db.scalar(select(func.count(User.id)).where(User.is_demo.is_(False))) or 0
        if real:
            return ("Refusing to seed: the database already contains real (non-demo) accounts. "
                    "Use a separate DATABASE_URL for demos.")
        if db.scalar(select(func.count(User.id))):
            return "Demo data already present; nothing changed."

        now = utcnow()
        admin = _user(db, f"admin@{DOMAIN}", "Demo Administrator", "admin")

        ngo_users = []
        for i, (name, lat, lon, prio, cap, dem, cats) in enumerate(NGOS, start=1):
            u = _user(db, f"ngo{i}@{DOMAIN}", f"{name} Coordinator", "ngo", org=name, phone=f"+91-90000-0000{i}")
            db.add(NGOProfile(user_id=u.id, org_name=name, address=f"{name}, Greater Noida (demo address)",
                              latitude=lat, longitude=lon, priority=prio, capacity_kg=cap, demand_kg=dem,
                              accepted_categories=",".join(sorted(cats)), contact_phone=u.phone))
            ngo_users.append(u)

        donors = {}
        for org, handle, lat, lon, addr in DONORS:
            donors[handle] = (_user(db, f"{handle}@{DOMAIN}", f"{org} Manager", "donor", org=org,
                                    phone="+91-90000-10000"), lat, lon, addr)

        vols = []
        for name, handle, lat, lon, vt, cap, rng in VOLUNTEERS:
            u = _user(db, f"{handle}@{DOMAIN}", name, "volunteer", phone="+91-90000-20000")
            db.add(VolunteerProfile(user_id=u.id, area="Greater Noida (demo)", latitude=lat, longitude=lon,
                                    is_available=True, vehicle_type=vt, vehicle_capacity_kg=cap, max_distance_km=rng))
            vols.append(u)
        db.flush()
        audit(db, admin.id, "demo_seeded", "system", None)

        def donate(handle, food, cat, qty, unit, kg, life_h, start_h, end_h, prep=None, notes=None):
            u, lat, lon, addr = donors[handle]
            d = Donation(donor_id=u.id, food_name=food, category=cat, quantity=qty, unit=unit, quantity_kg=kg,
                         preparation_details=prep, prepared_at=now - timedelta(hours=1), posted_at=now,
                         usable_life_hours=life_h, expires_at=now + timedelta(hours=life_h), pickup_address=addr,
                         latitude=lat, longitude=lon, pickup_start=now + timedelta(hours=start_h),
                         pickup_end=now + timedelta(hours=min(end_h, life_h)), notes=notes, status="posted")
            db.add(d)
            db.flush()
            audit(db, u.id, "donation_created", "donation", d.id, quantity_kg=kg, category=cat)
            generate_matches(db, d, u.id, now)
            return d

        offers = [
            donate("donor.hotel", "Veg biryani and dal (buffet surplus)", "prepared_meals", 60, "portions", 18, 5, 0, 3,
                   "Cooked 1 h ago, kept hot in chafing dishes", "Bring insulated containers"),
            donate("donor.bakery", "Assorted bread loaves", "bakery", 40, "items", 16, 20, 0, 6, "Baked this morning"),
            donate("donor.events", "Paneer curry and rotis", "prepared_meals", 25, "kg", 25, 4, 0, 3,
                   "Event leftovers, never served"),
            donate("donor.hotel", "Seasonal fruit platter", "fruits_vegetables", 12, "kg", 12, 10, 0.5, 8),
            donate("donor.bakery", "Packaged biscuits (sealed)", "packaged", 30, "packets", 9, 240, 1, 48,
                   "Sealed, within best-before date"),
            donate("donor.events", "Flavoured yoghurt cups", "dairy", 40, "items", 6, 8, 0, 6, "Refrigerated at 4°C"),
            donate("donor.hotel", "Steamed rice and rajma", "prepared_meals", 10, "kg", 10, 6, 0, 4),
        ]
        db.commit()

        # Drive a few offers through the real lifecycle so dashboards show every state.
        def top_match(d: Donation) -> MatchRecommendation | None:
            return db.scalar(select(MatchRecommendation).where(
                MatchRecommendation.donation_id == d.id, MatchRecommendation.status == "proposed")
                .order_by(MatchRecommendation.rank).limit(1))

        flow = [(offers[1], "delivered"), (offers[3], "picked_up"), (offers[4], "assigned"), (offers[2], "accepted")]
        for d, target in flow:
            m = top_match(d)
            if m is None:
                continue
            accept_match(db, m.id, db.get(User, m.ngo.user_id))
            if target == "accepted":
                continue
            db.refresh(d)
            for v in vols:
                try:
                    accept_task(db, d.task.id, db.get(User, v.id))
                    break
                except Exception:
                    db.rollback()
            db.refresh(d)
            if target in ("picked_up", "delivered") and d.task.volunteer_id:
                update_task_status(db, d.task.id, db.get(User, d.task.volunteer_id), "picked_up")
            if target == "delivered" and d.task.volunteer_id:
                update_task_status(db, d.task.id, db.get(User, d.task.volunteer_id), "delivered")
        db.commit()
    return (f"Seeded demo data: 1 admin, {len(NGOS)} NGOs, {len(DONORS)} donors, {len(VOLUNTEERS)} volunteers, "
            f"7 donations. Password for every demo account: value of DEMO_PASSWORD (default 'Demo@12345').")


if __name__ == "__main__":  # pragma: no cover
    print(seed())
