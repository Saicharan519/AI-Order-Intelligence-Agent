# Progress log

## Current milestone

**M0a complete (pending commit approval).** Next: M1 (data load) once the Olist CSVs are in `data/raw/`. M0b (DeepSeek calibration, paid) waits for an API key and explicit approval.

## 2026-10-15 — M0a: local environment (free)

**Completed**
- Reviewed PRD, technical design, and implementation plan; compared with the reference cold-chain project.
- Verified DeepSeek pricing page: model IDs and prices in PRD §13 are correct; `deepseek-v4-flash` is a retired legacy name; thinking mode is on by default (must be disabled per call).
- Applied 7 document corrections (all three docs now v1.1, each change in its document history): undelivered count 2,965; ablations measure SQL generation only; accuracy on answerable items with confidence intervals; non-thinking mode; LangGraph as wiring only with direct SDK calls; commits and paid calls need owner approval; dataset figures provisional until reproduced; M0 split into M0a/M0b.
- Git repository initialised (branch `main`, no commits yet). Design docs moved to `docs/`.
- PostgreSQL 18.6 in Docker Compose, bound to 127.0.0.1, named volume, healthcheck.
- Pinned dependencies; virtual environment `.venv` created; package installed in editable mode.
- Secret scanner (`scripts/check_secrets.py`) with pre-commit hook (`.githooks/pre-commit`).
- Local `.env` created with random per-role database passwords (values never printed). `DEEPSEEK_API_KEY` is empty.

**Files created:** `.gitignore`, `.gitattributes`, `.env.example`, `docker-compose.yml`, `requirements.txt`, `requirements-dev.txt`, `pyproject.toml`, `README.md`, `.githooks/pre-commit`, `scripts/check_secrets.py`, `tests/unit/test_check_secrets.py`, `src/orderintel/__init__.py`, `docs/environment.md`, `docs/progress.md`, `data/raw/.gitkeep`.
**Files modified:** `docs/PRD.md`, `docs/TECHNICAL_DESIGN.md`, `docs/IMPLEMENTATION_PLAN.md` (moved from root to `docs/`).

**Tests and checks (actually run)**

| Check | Result |
|---|---|
| `pip install -r requirements-dev.txt` and `pip check` | Passed |
| Import of all runtime packages | Passed (psycopg 3.3.6, sqlglot 30.23.0) |
| `pytest` (10 unit tests, secret scanner) | 10 passed |
| `ruff check .` | Passed (after fixing 3 findings) |
| `docker compose up -d db` | Container healthy; `PostgreSQL 18.6` confirmed via `psql` |
| Port binding | `127.0.0.1:5432->5432/tcp` (localhost only) |
| `.env` and `data/raw/*` ignored by git | Confirmed with `git check-ignore` |
| Secret scan, all files | Passed (20 files) |
| Hook blocks force-staged `.env` | Blocked (exit 1); file unstaged afterwards |
| Hook blocks a file containing a real `.env` password | Blocked (exit 1), value not printed; test file removed |

**Issues found and fixed**
- The scanner flagged its own Python constants (`SECRET_NAME = ...`) as secrets. The env-assignment rule now matches only `KEY=value` without spaces (env-file and shell syntax); a regression test was added. The exact-value check against `.env` remains the main guard.

**Known issues / decisions**
- Project stays in OneDrive by owner's choice; `.env` is synced to OneDrive (not GitHub).
- Docker Desktop showed a "lingering processes" dialog on start-up; resolved by stopping the stale processes.

**API cost incurred:** $0.00

## Next steps
1. Owner reviews and approves the initial commit.
2. M1: owner downloads the Olist dataset into `data/raw/`; then typed raw tables, loader, and count checks.
3. M0b (any time before M5): owner creates a DeepSeek key in `.env`; calibration of about 10 calls (< $0.01) after approval.
