"""Pydantic request/response schemas with validation rules."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Generic, Literal, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from .models import FOOD_CATEGORIES, UNITS

T = TypeVar("T")

Category = Literal["prepared_meals", "bakery", "fruits_vegetables", "dairy", "packaged"]
Unit = Literal["kg", "litres", "portions", "items", "packets"]


def _to_naive_utc(v: Optional[datetime]) -> Optional[datetime]:
    if v is None:
        return None
    if v.tzinfo is not None:
        v = v.astimezone(timezone.utc).replace(tzinfo=None)
    return v


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


class Message(BaseModel):
    message: str


# ---------------------------------------------------------------------------
# Auth / users
# ---------------------------------------------------------------------------
class NGORegistration(BaseModel):
    org_name: str = Field(min_length=2, max_length=160)
    address: str = Field(min_length=3, max_length=255)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    priority: float = Field(0.5, ge=0, le=1)
    capacity_kg: float = Field(0, ge=0, le=100000)
    demand_kg: float = Field(0, ge=0, le=100000)
    accepted_categories: list[Category] = Field(min_length=1)
    contact_phone: Optional[str] = Field(None, max_length=30)


class VolunteerRegistration(BaseModel):
    area: str = Field("", max_length=160)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    is_available: bool = True
    vehicle_type: str = Field("bike", max_length=40)
    vehicle_capacity_kg: float = Field(20, gt=0, le=5000)
    max_distance_km: float = Field(10, gt=0, le=200)
    constraints: Optional[str] = Field(None, max_length=255)


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    full_name: str = Field(min_length=2, max_length=120)
    phone: Optional[str] = Field(None, max_length=30)
    organization: Optional[str] = Field(None, max_length=160)
    role: Literal["donor", "ngo", "volunteer"]  # admins are created via CLI only
    ngo: Optional[NGORegistration] = None
    volunteer: Optional[VolunteerRegistration] = None

    @field_validator("password")
    @classmethod
    def strong_password(cls, v: str) -> str:
        if not any(c.isalpha() for c in v) or not any(c.isdigit() for c in v):
            raise ValueError("password must contain at least one letter and one digit")
        return v

    @model_validator(mode="after")
    def role_profile(self):
        if self.role == "ngo" and self.ngo is None:
            raise ValueError("NGO registration requires organisation details")
        if self.role == "volunteer" and self.volunteer is None:
            raise ValueError("volunteer registration requires location details")
        return self


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=72)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: str
    full_name: str
    phone: Optional[str]
    organization: Optional[str]
    role: str
    is_active: bool
    is_demo: bool
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class NGOOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int
    org_name: str
    address: str
    latitude: float
    longitude: float
    priority: float
    capacity_kg: float
    demand_kg: float
    categories: list[str]
    contact_phone: Optional[str]
    updated_at: datetime


class NGOUpdate(BaseModel):
    address: Optional[str] = Field(None, min_length=3, max_length=255)
    latitude: Optional[float] = Field(None, ge=-90, le=90)
    longitude: Optional[float] = Field(None, ge=-180, le=180)
    priority: Optional[float] = Field(None, ge=0, le=1)
    capacity_kg: Optional[float] = Field(None, ge=0, le=100000)
    demand_kg: Optional[float] = Field(None, ge=0, le=100000)
    accepted_categories: Optional[list[Category]] = Field(None, min_length=1)
    contact_phone: Optional[str] = Field(None, max_length=30)


class VolunteerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int
    area: str
    latitude: float
    longitude: float
    is_available: bool
    vehicle_type: str
    vehicle_capacity_kg: float
    max_distance_km: float
    constraints: Optional[str]


class VolunteerUpdate(BaseModel):
    area: Optional[str] = Field(None, max_length=160)
    latitude: Optional[float] = Field(None, ge=-90, le=90)
    longitude: Optional[float] = Field(None, ge=-180, le=180)
    is_available: Optional[bool] = None
    vehicle_type: Optional[str] = Field(None, max_length=40)
    vehicle_capacity_kg: Optional[float] = Field(None, gt=0, le=5000)
    max_distance_km: Optional[float] = Field(None, gt=0, le=200)
    constraints: Optional[str] = Field(None, max_length=255)


class MeOut(BaseModel):
    user: UserOut
    ngo: Optional[NGOOut] = None
    volunteer: Optional[VolunteerOut] = None


# ---------------------------------------------------------------------------
# Donations
# ---------------------------------------------------------------------------
class DonationCreate(BaseModel):
    food_name: str = Field(min_length=2, max_length=160)
    category: Category
    quantity: float = Field(gt=0, le=100000)
    unit: Unit
    quantity_kg: Optional[float] = Field(None, gt=0, le=100000, description="Estimated weight; required unless unit is kg/litres")
    preparation_details: Optional[str] = Field(None, max_length=1000)
    prepared_at: Optional[datetime] = None
    usable_life_hours: float = Field(gt=0, le=24 * 365)
    pickup_address: str = Field(min_length=3, max_length=255)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    pickup_start: datetime
    pickup_end: datetime
    notes: Optional[str] = Field(None, max_length=1000)

    _norm = field_validator("prepared_at", "pickup_start", "pickup_end")(lambda v: _to_naive_utc(v))

    @model_validator(mode="after")
    def check(self):
        if self.unit in ("kg", "litres"):
            # 1 litre of food is approximated as 1 kg for matching purposes.
            self.quantity_kg = self.quantity_kg or self.quantity
        elif self.quantity_kg is None:
            raise ValueError("estimated weight in kg (quantity_kg) is required for this unit")
        if self.pickup_end <= self.pickup_start:
            raise ValueError("pickup window end must be after its start")
        return self


class DonationUpdate(BaseModel):
    notes: Optional[str] = Field(None, max_length=1000)
    preparation_details: Optional[str] = Field(None, max_length=1000)
    pickup_start: Optional[datetime] = None
    pickup_end: Optional[datetime] = None

    _norm = field_validator("pickup_start", "pickup_end")(lambda v: _to_naive_utc(v))


class DonationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    donor_id: int
    donor_name: Optional[str] = None
    donor_org: Optional[str] = None
    food_name: str
    category: str
    category_label: str = ""
    quantity: float
    unit: str
    quantity_kg: float
    preparation_details: Optional[str]
    prepared_at: Optional[datetime]
    posted_at: datetime
    usable_life_hours: float
    expires_at: datetime
    remaining_hours: float = 0
    pickup_address: str
    latitude: float
    longitude: float
    pickup_start: datetime
    pickup_end: datetime
    notes: Optional[str]
    image_url: Optional[str] = None
    status: str
    ngo_id: Optional[int]
    ngo_name: Optional[str] = None
    task_status: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class MatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    donation_id: int
    ngo_id: int
    ngo_name: Optional[str] = None
    rank: int
    score: float
    freshness: float
    proximity: float
    capacity_fit: float
    demand_fit: float
    priority: float
    distance_km: float
    explanation: str
    status: str
    created_at: datetime
    decided_at: Optional[datetime]


class RejectRequest(BaseModel):
    reason: Optional[str] = Field(None, max_length=300)


class TaskOut(BaseModel):
    id: int
    donation_id: int
    status: str
    distance_km: float
    volunteer_id: Optional[int]
    volunteer_name: Optional[str] = None
    created_at: datetime
    accepted_at: Optional[datetime]
    picked_up_at: Optional[datetime]
    delivered_at: Optional[datetime]
    food_name: str
    category: str
    quantity_kg: float
    remaining_hours: float
    pickup_address: str
    pickup_lat: float
    pickup_lon: float
    pickup_start: datetime
    pickup_end: datetime
    donor_name: Optional[str] = None
    donor_phone: Optional[str] = None
    ngo_name: str
    ngo_address: str
    ngo_lat: float
    ngo_lon: float
    ngo_phone: Optional[str] = None
    distance_from_you_km: Optional[float] = None
    eligible: Optional[bool] = None
    ineligible_reason: Optional[str] = None


class TaskStatusUpdate(BaseModel):
    status: Literal["picked_up", "delivered"]


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    kind: str
    message: str
    link: Optional[str]
    is_read: bool
    created_at: datetime


class ReportCreate(BaseModel):
    entity_type: Literal["donation", "user"]
    entity_id: int = Field(gt=0)
    reason: str = Field(min_length=5, max_length=500)


class ReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    reporter_id: int
    reporter_name: Optional[str] = None
    entity_type: str
    entity_id: int
    reason: str
    status: str
    resolution_note: Optional[str]
    created_at: datetime
    resolved_at: Optional[datetime]


class ReportResolve(BaseModel):
    status: Literal["resolved", "dismissed"]
    resolution_note: Optional[str] = Field(None, max_length=500)
    deactivate_user: bool = False
    cancel_donation: bool = False


class UserActiveUpdate(BaseModel):
    is_active: bool


class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    actor_id: Optional[int]
    actor_name: Optional[str] = None
    action: str
    entity_type: str
    entity_id: Optional[int]
    details: Optional[str]
    created_at: datetime


assert set(FOOD_CATEGORIES) == {"prepared_meals", "bakery", "fruits_vegetables", "dairy", "packaged"}
assert set(UNITS) == {"kg", "litres", "portions", "items", "packets"}
