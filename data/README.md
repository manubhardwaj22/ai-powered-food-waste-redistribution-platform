# data/

Runtime data lives here and is **not committed** (see `.gitignore`):

| File / folder | Created by | Contents |
|---|---|---|
| `foodrescue.db` | `python run.py init-db` / first start | SQLite database (users, donations, matches, tasks, notifications, audit log) |
| `uploads/` | donors uploading photos | Donation images with random filenames |
| `benchmark_results.json` | `python run.py benchmark` or the admin dashboard | Latest synthetic benchmark results |

The synthetic benchmark dataset is not stored as a file: it is regenerated deterministically from
random seed 7 by `backend/app/benchmark.py` every time it runs.

Demo data (`python run.py seed`) is fictional and uses the reserved `foodrescue.example` email domain.
