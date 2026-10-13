# Testing Report

Date: 13 October 2026 · Environment: Linux, Python 3.13, FastAPI 0.143, SQLAlchemy 2.1,
Chromium (Playwright) for UI checks. Windows was **not** available for testing; the README's
Windows commands are standard `venv`/`pip` commands but were not executed on Windows.

## Automated tests (pytest)

Command: `cd backend && python -m pytest` — uses a separate temporary SQLite database.

**Result: 69 passed, 0 failed (≈23 s).**

| File | Tests | Covers |
|---|---:|---|
| `test_matching.py` | 36 | weights sum to 1; F, G, C, Q, P formulas; Haversine; zero / negative / NaN inputs; weighted score; feasibility (category, capacity, demand, radius, invalid coords, inactive, declined); invalid donations (expired, closed window, wrong status, zero qty, bad coords, window after expiry); volunteer feasibility; ranking order; priority tie-break; limit and explanations |
| `test_auth.py` | 9 | register/login, bcrypt hash stored, duplicate email, weak passwords, missing role profiles, no admin self-registration, invalid login, 401 for missing/bad token, 403 role enforcement, deactivated accounts |
| `test_donations.py` | 9 | auto-matching on create, no-feasible case, field validation (category, quantity, coordinates, life, kg estimate, pickup windows), ownership isolation, expiry sweep, one-time expiry warning, cancel releases capacity, persistence across sessions, image upload validation |
| `test_workflow.py` | 9 | full posted → delivered lifecycle with notifications, audit log and stats; duplicate acceptance (same and different NGO); **3-thread concurrent acceptance → exactly one wins**; cross-NGO acceptance blocked; capacity/category changes remove recommendations; decline + re-match excluding the decliner; volunteer eligibility (capacity, distance, availability), task ownership, invalid transitions; reports + admin resolution; 404s; public metadata, security headers |
| `test_benchmark.py` | 6 | dataset matches report totals, seed reproducibility, metric ranges and definitions, waste = 100 − fulfilment, proposed vs baselines, reference values kept separate, hand-checked tiny case |

## Manual / browser verification (Chromium via Playwright)

With the server running (`python run.py serve`) on seeded demo data:

| Workflow | Result |
|---|---|
| Landing, about, login, register pages render; scoring calculator updates live | Pass |
| Donor signs in, fills the "Post a donation" form (items unit + kg estimate), submits, lands on match details with score breakdowns | Pass |
| Donor donation list with status filters; notifications panel | Pass |
| NGO sees the new offer on its dashboard and accepts it | Pass |
| Volunteer sees the task, accepts, confirms pickup and delivery | Pass |
| Donor sees the donation as Delivered with the timeline | Pass |
| Admin dashboard loads stats, tables, audit log; "Run benchmark" regenerates results and charts | Pass |
| Mobile (390 px): landing, NGO and volunteer dashboards, slide-in menu; no horizontal overflow | Pass |
| Browser console | No JavaScript errors and no failed API calls. The only console errors were Google Fonts requests blocked by the test sandbox's network; pages fall back to system fonts. |

## Commands verified
`python run.py init-db`, `python run.py seed` (and re-running it: "already present"),
`python run.py benchmark`, `python run.py serve`.

## Not tested / limitations
- Windows-specific execution of the README steps.
- Real-device geolocation (the "Use my current location" button) — browser permission flows
  were not exercised; manual coordinate entry was.
- Load/performance testing beyond the concurrency test.
- Email/SMS delivery (not implemented by design).
