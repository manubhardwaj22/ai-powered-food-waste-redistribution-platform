"""Application configuration loaded from environment variables.

Values are read from the process environment. `run.py` loads a local `.env`
file (if present) before this module is imported, so developers can keep
secrets out of source control. See `.env.example` for every supported key.
"""
from __future__ import annotations

import os
import secrets
import warnings
from pathlib import Path

# Repository root: backend/app/config.py -> parents[2]
PROJECT_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIR = PROJECT_ROOT / "frontend"
DATA_DIR = PROJECT_ROOT / "data"
DOCS_DIR = PROJECT_ROOT / "docs"
CHARTS_DIR = DOCS_DIR / "charts"


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


APP_ENV = os.getenv("APP_ENV", "development")
IS_DEV = APP_ENV != "production"


def _resolve_sqlite(url: str) -> str:
    """Make relative SQLite paths relative to the project root, not the current directory."""
    prefix = "sqlite:///"
    if url.startswith(prefix) and not url.startswith(prefix + "/"):
        path = Path(url[len(prefix):])
        if not path.is_absolute() and str(path) != ":memory:":
            return prefix + (PROJECT_ROOT / path).as_posix()
    return url


DATABASE_URL = _resolve_sqlite(os.getenv("DATABASE_URL", f"sqlite:///{(DATA_DIR / 'foodrescue.db').as_posix()}"))
_upload = Path(os.getenv("UPLOAD_DIR", str(DATA_DIR / "uploads")))
UPLOAD_DIR = _upload if _upload.is_absolute() else PROJECT_ROOT / _upload

_secret = os.getenv("SECRET_KEY", "")
if not _secret or _secret.startswith("change-me"):
    if not IS_DEV:
        raise RuntimeError("SECRET_KEY must be set to a strong random value in production.")
    # Development fallback: a random per-process key. Tokens stop working after a restart.
    warnings.warn("SECRET_KEY not set; using a temporary random key (development only).")
    _secret = secrets.token_urlsafe(48)
SECRET_KEY = _secret

TOKEN_EXPIRE_MINUTES = int(os.getenv("TOKEN_EXPIRE_MINUTES", "480"))
JWT_ALGORITHM = "HS256"

# When true, a donor->NGO pair is only feasible if at least one available
# volunteer can reach the pickup point with enough vehicle capacity.
REQUIRE_VOLUNTEER_FEASIBILITY = _bool("REQUIRE_VOLUNTEER_FEASIBILITY", False)

# Maximum donor->NGO distance (km) considered feasible in the live application.
MAX_MATCH_DISTANCE_KM = float(os.getenv("MAX_MATCH_DISTANCE_KM", "25"))

# How many ranked recommendations to store per donation.
MAX_RECOMMENDATIONS = int(os.getenv("MAX_RECOMMENDATIONS", "5"))

# Send an "expiring soon" notification when remaining life drops below this many hours.
EXPIRY_WARNING_HOURS = float(os.getenv("EXPIRY_WARNING_HOURS", "2"))

# Background maintenance interval (expiry sweep) in seconds; 0 disables the loop.
MAINTENANCE_INTERVAL_SECONDS = int(os.getenv("MAINTENANCE_INTERVAL_SECONDS", "60"))

# Password used for demo accounts created by the explicit `seed` command.
DEMO_PASSWORD = os.getenv("DEMO_PASSWORD", "Demo@12345")

MAX_IMAGE_BYTES = 2 * 1024 * 1024
