"""Password hashing (bcrypt), JWT bearer tokens and role-based dependencies."""
from __future__ import annotations

import time
from collections import defaultdict, deque
from datetime import timedelta
from typing import Callable

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from . import config
from .database import get_db, utcnow
from .models import User

_bearer = HTTPBearer(auto_error=False)


# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------
def hash_password(password: str) -> str:
    # bcrypt only uses the first 72 bytes; schemas cap passwords at 72 chars.
    return bcrypt.hashpw(password.encode("utf-8")[:72], bcrypt.gensalt(rounds=12)).decode("ascii")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8")[:72], hashed.encode("ascii"))
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------
def create_access_token(user: User) -> str:
    now = utcnow()
    payload = {
        "sub": str(user.id),
        "role": user.role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=config.TOKEN_EXPIRE_MINUTES)).timestamp()),
    }
    return jwt.encode(payload, config.SECRET_KEY, algorithm=config.JWT_ALGORITHM)


def _unauthorized(detail: str = "Not authenticated") -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, detail=detail, headers={"WWW-Authenticate": "Bearer"})


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    if creds is None or creds.scheme.lower() != "bearer":
        raise _unauthorized()
    try:
        payload = jwt.decode(creds.credentials, config.SECRET_KEY, algorithms=[config.JWT_ALGORITHM])
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise _unauthorized("Invalid or expired token")
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise _unauthorized("Account not found or deactivated")
    return user


def require_roles(*roles: str) -> Callable[..., User]:
    """Dependency factory: allow only the given roles (enforced server-side)."""

    def dep(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="You do not have permission for this action")
        return user

    return dep


# ---------------------------------------------------------------------------
# Very small in-memory login throttle (per client IP + email)
# ---------------------------------------------------------------------------
_attempts: dict[str, deque] = defaultdict(deque)
MAX_ATTEMPTS = 10
WINDOW_SECONDS = 300


def check_login_rate(request: Request, email: str) -> None:
    key = f"{request.client.host if request.client else 'unknown'}|{email.lower()}"
    q = _attempts[key]
    now = time.monotonic()
    while q and now - q[0] > WINDOW_SECONDS:
        q.popleft()
    if len(q) >= MAX_ATTEMPTS:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many login attempts. Try again later.")
    q.append(now)


def reset_login_rate(request: Request, email: str) -> None:
    key = f"{request.client.host if request.client else 'unknown'}|{email.lower()}"
    _attempts.pop(key, None)
