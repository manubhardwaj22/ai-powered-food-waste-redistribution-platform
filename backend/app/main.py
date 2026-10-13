"""FastAPI application: API routers + static frontend served from the same origin."""
from __future__ import annotations

import asyncio
import contextlib
import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import IntegrityError

from . import config
from .database import SessionLocal, init_db
from .routes import (
    admin_routes,
    auth_routes,
    common_routes,
    donation_routes,
    matching_routes,
    ngo_routes,
    volunteer_routes,
)
from .services import run_maintenance

log = logging.getLogger("foodrescue")


async def _maintenance_loop() -> None:
    while True:
        await asyncio.sleep(config.MAINTENANCE_INTERVAL_SECONDS)
        try:
            with SessionLocal() as db:
                run_maintenance(db)
        except Exception:  # pragma: no cover - keep the loop alive
            log.exception("maintenance sweep failed")


@contextlib.asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    task = None
    if config.MAINTENANCE_INTERVAL_SECONDS > 0:
        with SessionLocal() as db:
            run_maintenance(db)
        task = asyncio.create_task(_maintenance_loop())
    yield
    if task:
        task.cancel()


app = FastAPI(
    title="FoodRescue AI API",
    description="AI-Powered Food Waste Donation & Redistribution Platform (Team 56, Bennett University).",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if config.IS_DEV else None,
    redoc_url="/redoc" if config.IS_DEV else None,
    openapi_url="/openapi.json" if config.IS_DEV else None,
)

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; img-src 'self' data: blob:; connect-src 'self'; "
    "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(self)")
    # Swagger UI loads its own CDN assets, so the strict CSP is applied to the app pages only.
    if not request.url.path.startswith(("/docs", "/redoc")):
        response.headers.setdefault("Content-Security-Policy", CSP)
    if request.url.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


@app.exception_handler(IntegrityError)
async def integrity_handler(_: Request, exc: IntegrityError):
    return JSONResponse(status_code=409, content={"detail": "The request conflicts with existing data."})


@app.get("/api/health", tags=["common"])
def health():
    return {"status": "ok", "environment": config.APP_ENV}


for r in (auth_routes, donation_routes, matching_routes, ngo_routes, volunteer_routes, admin_routes, common_routes):
    app.include_router(r.router)

config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
config.CHARTS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=config.UPLOAD_DIR), name="uploads")
app.mount("/charts", StaticFiles(directory=config.CHARTS_DIR), name="charts")
# The frontend is mounted last so /api/* routes take precedence.
app.mount("/", StaticFiles(directory=config.FRONTEND_DIR, html=True), name="frontend")
