"""In-app notifications and audit logging helpers.

Both write into the caller's session; the caller commits as part of its own
transaction so a notification is never stored for a change that rolled back.
"""
from __future__ import annotations

import json
from typing import Any, Iterable, Optional

from sqlalchemy.orm import Session

from .models import AuditLog, Notification


def notify(db: Session, user_id: int, kind: str, message: str, link: Optional[str] = None) -> Notification:
    n = Notification(user_id=user_id, kind=kind, message=message[:500], link=link)
    db.add(n)
    return n


def notify_many(db: Session, user_ids: Iterable[int], kind: str, message: str, link: Optional[str] = None) -> None:
    for uid in {u for u in user_ids if u is not None}:
        notify(db, uid, kind, message, link)


def audit(
    db: Session,
    actor_id: Optional[int],
    action: str,
    entity_type: str,
    entity_id: Optional[int],
    **details: Any,
) -> AuditLog:
    entry = AuditLog(
        actor_id=actor_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        details=json.dumps(details, default=str) if details else None,
    )
    db.add(entry)
    return entry
