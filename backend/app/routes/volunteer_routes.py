"""Volunteer / driver endpoints: availability, task board and status updates."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import require_roles
from ..database import get_db
from ..models import DeliveryTask, Donation, User, VolunteerProfile
from ..notifications import audit
from ..schemas import TaskOut, TaskStatusUpdate, VolunteerOut, VolunteerUpdate
from ..serializers import task_out
from ..services import accept_task, update_task_status

router = APIRouter(prefix="/api/volunteer", tags=["volunteer"])


def _profile(user: User) -> VolunteerProfile:
    if user.volunteer_profile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Volunteer profile not found")
    return user.volunteer_profile


@router.get("/profile", response_model=VolunteerOut)
def get_profile(user: User = Depends(require_roles("volunteer"))):
    return VolunteerOut.model_validate(_profile(user))


@router.patch("/profile", response_model=VolunteerOut)
def update_profile(body: VolunteerUpdate, user: User = Depends(require_roles("volunteer")),
                   db: Session = Depends(get_db)):
    v = _profile(user)
    data = body.model_dump(exclude_unset=True)
    for k, val in data.items():
        setattr(v, k, val)
    audit(db, user.id, "volunteer_profile_updated", "volunteer", v.id, fields=list(data))
    db.commit()
    db.refresh(v)
    return VolunteerOut.model_validate(v)


@router.get("/tasks/available", response_model=list[TaskOut])
def available_tasks(user: User = Depends(require_roles("volunteer")), db: Session = Depends(get_db)):
    """Open pickup tasks, nearest first, with an eligibility verdict for this volunteer.

    Contact details are withheld until the volunteer accepts the task.
    """
    v = _profile(user)
    rows = db.scalars(select(DeliveryTask).join(Donation).where(
        DeliveryTask.status == "open", Donation.status == "accepted")).all()
    out = [task_out(t, viewer=v, include_contacts=False) for t in rows]
    out.sort(key=lambda t: (not t.eligible, t.distance_from_you_km if t.distance_from_you_km is not None else 1e9))
    return out


@router.get("/tasks/mine", response_model=list[TaskOut])
def my_tasks(user: User = Depends(require_roles("volunteer")), db: Session = Depends(get_db)):
    v = _profile(user)
    rows = db.scalars(select(DeliveryTask).where(DeliveryTask.volunteer_id == user.id)
                      .order_by(DeliveryTask.accepted_at.desc())).all()
    return [task_out(t, viewer=v, include_contacts=True) for t in rows]


@router.post("/tasks/{task_id}/accept", response_model=TaskOut)
def accept(task_id: int, user: User = Depends(require_roles("volunteer")), db: Session = Depends(get_db)):
    t = accept_task(db, task_id, user)
    return task_out(t, viewer=_profile(user))


@router.post("/tasks/{task_id}/status", response_model=TaskOut)
def set_status(task_id: int, body: TaskStatusUpdate, user: User = Depends(require_roles("volunteer")),
               db: Session = Depends(get_db)):
    t = update_task_status(db, task_id, user, body.status)
    return task_out(t, viewer=_profile(user))
