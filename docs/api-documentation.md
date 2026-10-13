# API Documentation

Interactive documentation (Swagger UI) is available at **http://127.0.0.1:8000/docs** while
`APP_ENV=development` (ReDoc at `/redoc`). It is disabled in production.

All endpoints are under `/api`. Authenticated endpoints need `Authorization: Bearer <token>`.

**Conventions**
- Errors: `{"detail": "..."}`; validation errors (422) return FastAPI's list format.
- `401` not signed in / invalid token · `403` wrong role or not your resource · `404` not found or
  not visible to you · `409` invalid state transition, duplicate, or capacity conflict ·
  `413/415` bad upload · `422` validation · `429` too many login attempts.
- Paginated lists: `?page=1&page_size=20` → `{"items", "total", "page", "page_size"}`.

## Auth
| Method | Path | Who | Description |
|---|---|---|---|
| POST | `/api/auth/register` | public | Register donor / ngo / volunteer (`ngo` or `volunteer` object required for those roles). Returns token. |
| POST | `/api/auth/login` | public | Email + password → `{access_token, user}` |
| GET | `/api/auth/me` | any | Current user + NGO / volunteer profile |
| PATCH | `/api/auth/me` | any | Update name, phone, organisation |

## Donations (donor)
| Method | Path | Description |
|---|---|---|
| POST | `/api/donations` | Create; runs matching immediately |
| GET | `/api/donations?status=` | My donations (paginated) |
| GET | `/api/donations/summary` | Counts and kg by status |
| GET | `/api/donations/{id}` | Detail (also visible to recommended/assigned NGO, assigned volunteer, admin) |
| PATCH | `/api/donations/{id}` | Edit notes / handling / pickup window while open |
| POST | `/api/donations/{id}/cancel` | Cancel (posted, matched or accepted) |
| POST | `/api/donations/{id}/image` | Upload photo (multipart `file`) |

Example body for `POST /api/donations`:
```json
{
  "food_name": "Veg biryani", "category": "prepared_meals",
  "quantity": 60, "unit": "portions", "quantity_kg": 18,
  "usable_life_hours": 5, "prepared_at": "2026-10-13T12:00:00Z",
  "pickup_address": "Hotel kitchen", "latitude": 28.4675, "longitude": 77.5134,
  "pickup_start": "2026-10-13T13:00:00Z", "pickup_end": "2026-10-13T16:00:00Z",
  "notes": "Bring insulated bags"
}
```
Categories: `prepared_meals, bakery, fruits_vegetables, dairy, packaged`.
Units: `kg, litres, portions, items, packets` (`quantity_kg` required unless kg/litres).

## Matching
| Method | Path | Who | Description |
|---|---|---|---|
| GET | `/api/matches/weights` | public | Weights and formulas |
| GET | `/api/matches/donation/{id}?include_history=` | visible parties | Ranked recommendations with F, G, C, Q, P, score, distance, explanation |
| POST | `/api/matches/donation/{id}/run` | donor owner, admin | Recompute recommendations |
| POST | `/api/matches/{match_id}/accept` | recommended NGO | Atomic acceptance; creates delivery task |
| POST | `/api/matches/{match_id}/reject` | recommended NGO | Decline with optional `reason`; re-matches if no candidates remain |

## NGO
| Method | Path | Description |
|---|---|---|
| GET / PATCH | `/api/ngo/profile` | View / update capacity, demand, priority, categories, location (re-runs matching) |
| GET | `/api/ngo/recommendations` | Offers currently proposed to me |
| GET | `/api/ngo/donations?status=` | Donations assigned to me |
| GET | `/api/ngo/stats` | Impact statistics |

## Volunteer
| Method | Path | Description |
|---|---|---|
| GET / PATCH | `/api/volunteer/profile` | Location, availability, vehicle capacity, max distance |
| GET | `/api/volunteer/tasks/available` | Open tasks with eligibility verdict and distance from me |
| GET | `/api/volunteer/tasks/mine` | My tasks (with contacts) |
| POST | `/api/volunteer/tasks/{id}/accept` | Claim a task (atomic) |
| POST | `/api/volunteer/tasks/{id}/status` | `{"status": "picked_up"}` then `{"status": "delivered"}` |

## Shared
| Method | Path | Description |
|---|---|---|
| GET | `/api/meta` | Categories and units |
| GET | `/api/notifications?unread_only=&limit=` | My notifications + unread count |
| POST | `/api/notifications/{id}/read` · `/api/notifications/read-all` | Mark read |
| POST | `/api/reports` | Report a donation or user to admins |
| GET | `/api/health` | Health check |

## Admin (role `admin` only)
| Method | Path | Description |
|---|---|---|
| GET | `/api/admin/stats` | Totals, status counts, delayed, kg offered/matched/delivered, activity |
| GET | `/api/admin/users?role=` | Users (paginated) |
| PATCH | `/api/admin/users/{id}/active` | Activate / deactivate |
| GET | `/api/admin/donations?status=&delayed=` | All donations |
| POST | `/api/admin/donations/{id}/cancel` | Cancel any open donation |
| GET | `/api/admin/ngos` | All NGOs |
| GET | `/api/admin/matches?status=` | All recommendations with components |
| GET | `/api/admin/audit?action=` | Audit log |
| GET | `/api/admin/reports?status=` · POST `/api/admin/reports/{id}/resolve` | Review reports |
| POST | `/api/admin/maintenance/run` | Expiry / warning sweep now |
| GET | `/api/admin/benchmark` · POST `/api/admin/benchmark/run` | Latest / regenerate synthetic benchmark |
