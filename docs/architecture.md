# System Architecture

```
 Browser (HTML5 + CSS3 + vanilla JS)
   index / login / register / about
   donor-, ngo-, volunteer-, admin-dashboard, create-donation, donations, match-details
        │  fetch() with JWT bearer token (same origin, no CORS)
        ▼
 FastAPI application (backend/app/main.py)
   ├── routes/            REST endpoints, Pydantic validation, role checks
   ├── auth.py            bcrypt hashing, JWT, require_roles(), login throttle
   ├── services.py        lifecycle state machine, atomic accept, cancel/expire, tasks
   ├── matching.py        pure scoring engine (no DB access)
   ├── notifications.py   in-app notifications + audit log writers
   ├── analytics.py       live admin statistics
   ├── benchmark.py       synthetic dataset + 4 methods + charts (NumPy/pandas/Matplotlib)
   └── seed.py            explicit, guarded demo data
        │  SQLAlchemy 2.0 ORM
        ▼
 SQLite (data/foodrescue.db, WAL mode, foreign keys on)
```

The frontend is served by FastAPI's `StaticFiles` from the same origin as the API, so no CORS
configuration is needed. Uploaded donation photos are served from `/uploads`, benchmark charts
from `/charts`.

## Data model

| Table | Purpose | Key constraints |
|---|---|---|
| `users` | All accounts; `role` ∈ donor/ngo/volunteer/admin | unique email, role CHECK |
| `ngo_profiles` | Location, priority P_j, available capacity c_j, unmet demand d_j, accepted categories | 1:1 user, CHECK capacity/demand ≥ 0, 0 ≤ priority ≤ 1 |
| `volunteer_profiles` | Location, availability, vehicle capacity, max travel distance | 1:1 user |
| `donations` | Offer details, expiry, pickup window, status, assigned NGO, reserved demand | CHECK quantity > 0, status CHECK, indexes on status/expiry |
| `match_recommendations` | One row per ranked candidate with all five components, score, explanation, status | index (donation, ngo) |
| `delivery_tasks` | Pickup/delivery job with volunteer and timestamps | unique per donation |
| `notifications` | Per-user in-app messages | index (user, is_read) |
| `audit_logs` | Actor, action, entity, JSON details for every important state change | index on action/time |
| `reports` | User-submitted reports of problematic donations/accounts | — |

## Donation state machine (enforced in `services.ALLOWED_TRANSITIONS`)

```
posted ──► matched ──► accepted ──► picked_up ──► delivered
  ▲  │        │  │         │
  └──┼────────┘  │         │       (matched → posted when all candidates decline)
     ▼           ▼         ▼
  cancelled / expired (from posted, matched or accepted)
```

- Only the **recommended NGO** can accept/decline its recommendation.
- Only the **assigned volunteer** can mark picked up → delivered, in that order.
- Only the **donor owner** (or an admin) can cancel.
- Expiry runs in a background sweep every `MAINTENANCE_INTERVAL_SECONDS` and on demand from the
  admin dashboard. Cancelling or expiring an accepted donation releases the NGO's reserved
  capacity and demand.

## Concurrency protection

`services.accept_match` uses compare-and-set updates inside one transaction:

1. `UPDATE donations SET status='accepted' WHERE id=? AND status IN ('posted','matched')` — must
   affect exactly 1 row, otherwise 409.
2. `UPDATE ngo_profiles SET capacity_kg = capacity_kg − q … WHERE id=? AND capacity_kg >= q` —
   must affect 1 row, otherwise the whole transaction rolls back.

SQLite serialises writers, so two simultaneous acceptances can never both succeed. The same
pattern protects volunteer task claiming. `test_concurrent_acceptance_only_one_wins` exercises
this with three threads.

## Security controls

- Passwords hashed with bcrypt (12 rounds); never stored or logged in plaintext.
- JWT (HS256) signed with `SECRET_KEY` from the environment; refused at startup in production
  if unset.
- Server-side role checks on every route (`require_roles`), plus ownership checks in services.
  The frontend's role redirects are convenience only.
- Admin accounts cannot be self-registered (CLI only).
- Pydantic validation on every request body; numeric ranges, enums, lengths, date windows.
- Login throttling (10 attempts / 5 min per IP + email).
- Security headers: CSP (`script-src 'self'`, no inline scripts), `X-Frame-Options: DENY`,
  `nosniff`, `Referrer-Policy`, `Cache-Control: no-store` on API responses.
- The frontend builds DOM with `textContent` only (no `innerHTML` of data) to prevent XSS.
- Image uploads: 2 MB limit, magic-byte check (JPEG/PNG/WebP), random filenames.
- Contact details for a task are revealed only to the volunteer who accepted it.
- Redirect targets after login are restricted to local page names.
- Demo seeding refuses to run when real accounts exist and never modifies existing rows.
