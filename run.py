"""FoodRescue AI command-line entry point.

Usage (from the project root, with the virtual environment active):

    python run.py init-db              Create tables (safe: never drops data)
    python run.py seed                 Load fictional demo data (refuses if real accounts exist)
    python run.py create-admin         Create an administrator account interactively
    python run.py benchmark            Run the synthetic benchmark and regenerate charts
    python run.py serve [--port 8000]  Start the web app at http://127.0.0.1:8000
"""
from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "backend"))


def load_env(path: Path = ROOT / ".env") -> None:
    """Minimal .env loader (KEY=VALUE lines). Existing environment variables win."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def cmd_init_db(_args) -> None:
    from app.database import init_db

    init_db()
    print("Database initialised (existing data left untouched).")


def cmd_seed(_args) -> None:
    from app.seed import seed

    print(seed())


def cmd_create_admin(args) -> None:
    from sqlalchemy import select

    from app.auth import hash_password
    from app.database import SessionLocal, init_db
    from app.models import User
    from app.notifications import audit

    init_db()
    email = (args.email or input("Admin email: ")).strip().lower()
    name = args.name or input("Full name: ").strip()
    password = getpass.getpass("Password (min 8 chars, letters + digits): ")
    if len(password) < 8 or not any(c.isdigit() for c in password) or not any(c.isalpha() for c in password):
        sys.exit("Password too weak.")
    with SessionLocal() as db:
        if db.scalar(select(User.id).where(User.email == email)):
            sys.exit("A user with that email already exists.")
        u = User(email=email, full_name=name or "Administrator", role="admin", password_hash=hash_password(password))
        db.add(u)
        db.flush()
        audit(db, u.id, "admin_created", "user", u.id)
        db.commit()
    print(f"Administrator {email} created.")


def cmd_benchmark(_args) -> None:
    import json

    from app import benchmark
    from app.config import CHARTS_DIR, DATA_DIR

    res = benchmark.run_and_save(DATA_DIR / "benchmark_results.json", CHARTS_DIR)
    print("SYNTHETIC benchmark (seed 7) - not a real-world evaluation\n")
    print(json.dumps(res["dataset"], indent=2))
    print(f"\n{'Method':<24}{'Fulfil %':>10}{'Waste %':>10}{'Urgent %':>10}{'Dist km':>10}{'Full %':>10}")
    for m in res["methods"].values():
        print(f"{m['label']:<24}{m['quantity_fulfillment_pct']:>10}{m['waste_ratio_pct']:>10}"
              f"{m['urgent_rescue_pct']:>10}{m['avg_distance_km']:>10}{m['full_match_pct']:>10}")
    r = res["reported_proposed_reference"]
    print(f"{'Report (reference)':<24}{r['quantity_fulfillment_pct']:>10}{r['waste_ratio_pct']:>10}"
          f"{r['urgent_rescue_pct']:>10}{r['avg_distance_km']:>10}{r['full_match_pct']:>10}")
    print("\nCharts written to docs/charts/, results to data/benchmark_results.json")


def cmd_serve(args) -> None:
    import uvicorn

    print(f"FoodRescue AI running at http://{args.host}:{args.port}  (API docs: /docs)")
    uvicorn.run("app.main:app", host=args.host, port=args.port, reload=args.reload,
                app_dir=str(ROOT / "backend"))


def main() -> None:
    load_env()
    p = argparse.ArgumentParser(description="FoodRescue AI management commands")
    sub = p.add_subparsers(dest="command")
    sub.add_parser("init-db").set_defaults(func=cmd_init_db)
    sub.add_parser("seed").set_defaults(func=cmd_seed)
    ca = sub.add_parser("create-admin")
    ca.add_argument("--email")
    ca.add_argument("--name")
    ca.set_defaults(func=cmd_create_admin)
    sub.add_parser("benchmark").set_defaults(func=cmd_benchmark)
    sv = sub.add_parser("serve")
    sv.add_argument("--host", default=os.getenv("HOST", "127.0.0.1"))
    sv.add_argument("--port", type=int, default=int(os.getenv("PORT", "8000")))
    sv.add_argument("--reload", action="store_true")
    sv.set_defaults(func=cmd_serve)
    args = p.parse_args()
    if not getattr(args, "func", None):
        args = p.parse_args(["serve"])
    args.func(args)


if __name__ == "__main__":
    main()
