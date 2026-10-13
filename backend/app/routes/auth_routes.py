"""Registration, login and current-user profile."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import (
    check_login_rate,
    create_access_token,
    get_current_user,
    hash_password,
    reset_login_rate,
    verify_password,
)
from ..database import get_db
from ..models import NGOProfile, User, VolunteerProfile
from ..notifications import audit
from ..schemas import LoginRequest, MeOut, NGOOut, RegisterRequest, TokenResponse, UserOut, VolunteerOut
from ..services import refresh_open_matches

router = APIRouter(prefix="/api/auth", tags=["auth"])


def me_payload(user: User) -> MeOut:
    return MeOut(
        user=UserOut.model_validate(user),
        ngo=NGOOut.model_validate(user.ngo_profile) if user.ngo_profile else None,
        volunteer=VolunteerOut.model_validate(user.volunteer_profile) if user.volunteer_profile else None,
    )


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(body: RegisterRequest, db: Session = Depends(get_db)):
    email = body.email.lower()
    if db.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="An account with this email already exists")
    user = User(
        email=email,
        password_hash=hash_password(body.password),
        full_name=body.full_name.strip(),
        phone=body.phone,
        organization=(body.ngo.org_name if body.ngo else body.organization),
        role=body.role,
    )
    db.add(user)
    db.flush()
    if body.role == "ngo" and body.ngo:
        n = body.ngo
        db.add(NGOProfile(user_id=user.id, org_name=n.org_name, address=n.address, latitude=n.latitude,
                          longitude=n.longitude, priority=n.priority, capacity_kg=n.capacity_kg,
                          demand_kg=n.demand_kg, accepted_categories=",".join(sorted(set(n.accepted_categories))),
                          contact_phone=n.contact_phone))
    if body.role == "volunteer" and body.volunteer:
        db.add(VolunteerProfile(user_id=user.id, **body.volunteer.model_dump()))
    audit(db, user.id, "user_registered", "user", user.id, role=user.role)
    db.flush()
    if body.role == "ngo":
        db.refresh(user)
        refresh_open_matches(db, user.id)  # a new NGO may be a better match for open offers
    db.commit()
    db.refresh(user)
    return TokenResponse(access_token=create_access_token(user), user=UserOut.model_validate(user))


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)):
    check_login_rate(request, body.email)
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="This account has been deactivated")
    reset_login_rate(request, body.email)
    return TokenResponse(access_token=create_access_token(user), user=UserOut.model_validate(user))


@router.get("/me", response_model=MeOut)
def me(user: User = Depends(get_current_user)):
    return me_payload(user)


class ProfileUpdate(BaseModel):
    full_name: str | None = Field(None, min_length=2, max_length=120)
    phone: str | None = Field(None, max_length=30)
    organization: str | None = Field(None, max_length=160)


@router.patch("/me", response_model=MeOut)
def update_me(body: ProfileUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(user, k, v)
    db.add(user)
    db.commit()
    db.refresh(user)
    return me_payload(user)
