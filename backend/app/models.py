"""Relational data model (SQLAlchemy 2.0 ORM)."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base, utcnow

# ---------------------------------------------------------------------------
# Domain vocabularies
# ---------------------------------------------------------------------------
ROLES = ("donor", "ngo", "volunteer", "admin")

FOOD_CATEGORIES = {
    "prepared_meals": "Prepared meals",
    "bakery": "Bakery products",
    "fruits_vegetables": "Fruits and vegetables",
    "dairy": "Dairy products",
    "packaged": "Packaged foods",
}

UNITS = ("kg", "litres", "portions", "items", "packets")

# Donation lifecycle: posted -> matched -> accepted -> picked_up -> delivered
# plus terminal cancelled / expired.
DONATION_STATUSES = ("posted", "matched", "accepted", "picked_up", "delivered", "cancelled", "expired")
OPEN_DONATION_STATUSES = ("posted", "matched")

MATCH_STATUSES = ("proposed", "accepted", "rejected", "superseded")
TASK_STATUSES = ("open", "accepted", "picked_up", "delivered", "cancelled")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[Optional[str]] = mapped_column(String(30))
    organization: Mapped[Optional[str]] = mapped_column(String(160))
    role: Mapped[str] = mapped_column(String(20), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    ngo_profile: Mapped[Optional["NGOProfile"]] = relationship(back_populates="user", uselist=False)
    volunteer_profile: Mapped[Optional["VolunteerProfile"]] = relationship(back_populates="user", uselist=False)

    __table_args__ = (CheckConstraint("role IN ('donor','ngo','volunteer','admin')", name="ck_user_role"),)


class NGOProfile(Base):
    """NGO / food bank: location, priority, available capacity and unmet demand."""

    __tablename__ = "ngo_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    org_name: Mapped[str] = mapped_column(String(160))
    address: Mapped[str] = mapped_column(String(255))
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    priority: Mapped[float] = mapped_column(Float, default=0.5)  # P_j in [0, 1]
    capacity_kg: Mapped[float] = mapped_column(Float, default=0.0)  # c_j (available)
    demand_kg: Mapped[float] = mapped_column(Float, default=0.0)  # d_j (unmet)
    accepted_categories: Mapped[str] = mapped_column(String(200), default="")  # comma-separated keys
    contact_phone: Mapped[Optional[str]] = mapped_column(String(30))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    user: Mapped[User] = relationship(back_populates="ngo_profile")

    __table_args__ = (
        CheckConstraint("priority >= 0 AND priority <= 1", name="ck_ngo_priority"),
        CheckConstraint("capacity_kg >= 0", name="ck_ngo_capacity"),
        CheckConstraint("demand_kg >= 0", name="ck_ngo_demand"),
    )

    @property
    def categories(self) -> list[str]:
        return [c for c in (self.accepted_categories or "").split(",") if c]


class VolunteerProfile(Base):
    __tablename__ = "volunteer_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    area: Mapped[str] = mapped_column(String(160), default="")
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    is_available: Mapped[bool] = mapped_column(Boolean, default=True)
    vehicle_type: Mapped[str] = mapped_column(String(40), default="bike")
    vehicle_capacity_kg: Mapped[float] = mapped_column(Float, default=20.0)
    max_distance_km: Mapped[float] = mapped_column(Float, default=10.0)
    constraints: Mapped[Optional[str]] = mapped_column(String(255))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    user: Mapped[User] = relationship(back_populates="volunteer_profile")


class Donation(Base):
    __tablename__ = "donations"

    id: Mapped[int] = mapped_column(primary_key=True)
    donor_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    food_name: Mapped[str] = mapped_column(String(160))
    category: Mapped[str] = mapped_column(String(40), index=True)
    quantity: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(20))
    quantity_kg: Mapped[float] = mapped_column(Float)  # q_i used by the matching engine
    preparation_details: Mapped[Optional[str]] = mapped_column(Text)
    prepared_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    posted_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    usable_life_hours: Mapped[float] = mapped_column(Float)  # stated at posting time
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    pickup_address: Mapped[str] = mapped_column(String(255))
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    pickup_start: Mapped[datetime] = mapped_column(DateTime)
    pickup_end: Mapped[datetime] = mapped_column(DateTime)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    image_path: Mapped[Optional[str]] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), default="posted", index=True)
    ngo_id: Mapped[Optional[int]] = mapped_column(ForeignKey("ngo_profiles.id"), index=True)
    # Demand (kg) deducted from the NGO on acceptance; restored if cancelled/expired.
    allocated_demand_kg: Mapped[float] = mapped_column(Float, default=0.0)
    expiry_warned: Mapped[bool] = mapped_column(Boolean, default=False)
    overdue_warned: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    donor: Mapped[User] = relationship(foreign_keys=[donor_id])
    ngo: Mapped[Optional[NGOProfile]] = relationship(foreign_keys=[ngo_id])
    task: Mapped[Optional["DeliveryTask"]] = relationship(back_populates="donation", uselist=False)

    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_donation_qty"),
        CheckConstraint("quantity_kg > 0", name="ck_donation_qty_kg"),
        CheckConstraint(
            "status IN ('posted','matched','accepted','picked_up','delivered','cancelled','expired')",
            name="ck_donation_status",
        ),
    )


class MatchRecommendation(Base):
    """One ranked donor->NGO candidate with its five score components."""

    __tablename__ = "match_recommendations"

    id: Mapped[int] = mapped_column(primary_key=True)
    donation_id: Mapped[int] = mapped_column(ForeignKey("donations.id", ondelete="CASCADE"), index=True)
    ngo_id: Mapped[int] = mapped_column(ForeignKey("ngo_profiles.id"), index=True)
    rank: Mapped[int] = mapped_column(Integer)
    score: Mapped[float] = mapped_column(Float)
    freshness: Mapped[float] = mapped_column(Float)
    proximity: Mapped[float] = mapped_column(Float)
    capacity_fit: Mapped[float] = mapped_column(Float)
    demand_fit: Mapped[float] = mapped_column(Float)
    priority: Mapped[float] = mapped_column(Float)
    distance_km: Mapped[float] = mapped_column(Float)
    explanation: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="proposed", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    decided_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))

    donation: Mapped[Donation] = relationship()
    ngo: Mapped[NGOProfile] = relationship()

    __table_args__ = (Index("ix_match_donation_ngo", "donation_id", "ngo_id"),)


class DeliveryTask(Base):
    __tablename__ = "delivery_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    donation_id: Mapped[int] = mapped_column(ForeignKey("donations.id", ondelete="CASCADE"), unique=True)
    ngo_id: Mapped[int] = mapped_column(ForeignKey("ngo_profiles.id"), index=True)
    volunteer_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    distance_km: Mapped[float] = mapped_column(Float)  # straight-line pickup -> NGO
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    accepted_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    picked_up_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    delivered_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    donation: Mapped[Donation] = relationship(back_populates="task")
    ngo: Mapped[NGOProfile] = relationship()
    volunteer: Mapped[Optional[User]] = relationship()


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    message: Mapped[str] = mapped_column(String(500))
    link: Mapped[Optional[str]] = mapped_column(String(255))
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), index=True)
    action: Mapped[str] = mapped_column(String(60), index=True)
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[Optional[int]] = mapped_column(Integer)
    details: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class Report(Base):
    """A user-submitted report about a problematic donation or account."""

    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    reporter_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    entity_type: Mapped[str] = mapped_column(String(20))  # donation | user
    entity_id: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)  # open | resolved | dismissed
    resolution_note: Mapped[Optional[str]] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    reporter: Mapped[User] = relationship()
