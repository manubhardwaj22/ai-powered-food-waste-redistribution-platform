"""API routers. Shared helpers for pagination live here."""
from __future__ import annotations

from typing import Callable, TypeVar

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

T = TypeVar("T")


def paginate(db: Session, stmt: Select, page: int, page_size: int, convert: Callable) -> dict:
    page = max(1, page)
    page_size = max(1, min(page_size, 100))
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = db.scalars(stmt.offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [convert(r) for r in rows], "total": total, "page": page, "page_size": page_size}
