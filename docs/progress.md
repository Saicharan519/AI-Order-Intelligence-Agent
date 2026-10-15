# Progress log

## Current milestone

**M1 complete (pending commit approval).** Next: M2 (database roles and the semantic layer). M0b (DeepSeek calibration, paid) waits for an API key and explicit approval.

## 2026-10-15 — M1: data load

**Completed**
- Olist CSVs placed in `data/raw/` by the owner; licence CC BY-NC-SA 4.0 recorded; SHA-256 checksums recorded (Q-01 resolved: files are not redistributed).
- `scripts/migrate.py`: creates `oi_owner` (NOSUPERUSER, NOCREATEDB, NOCREATEROLE) with its password from `.env`; revokes PUBLIC access to the database and `public` schema; applies numbered SQL migrations as `oi_owner`, tracked with checksums in `meta.schema_migrations`.
- Migration `001_raw_schema.sql`: eight typed `raw.*` tables (timestamps, `numeric(12,2)` money, `smallint` scores, text zip codes, surrogate key for reviews).
- `scripts/load_data.py`: atomic, idempotent load (truncate + reload in one transaction), CSV parsed in Python, streamed with COPY into staging, cast into typed tables, header and row-count verification.
- `scripts/check_counts.py`: 49 checks; reproduces every dataset figure in PRD sections 5.2–5.3 on raw tables; writes `docs/data_profile.md`.

**Files created:** `src/orderintel/config.py`, `src/orderintel/db/{__init__,connect}.py`, `db/migrations/001_raw_schema.sql`, `scripts/{migrate,load_data,check_counts}.py`, `tests/integration/test_load_data.py`, `tests/unit/test_check_counts.py`, `docs/data_notes.md`, `docs/data_profile.md`.
**Files modified:** `README.md` (data steps, troubleshooting), `docs/PRD.md` and `docs/TECHNICAL_DESIGN.md` (v1.2, small-seller figure), `docs/progress.md`.

**Tests and checks (actually run)**

| Check | Result |
|---|---|
| Migrations, first run and re-run | Applied, then skipped; all tables owned by `oi_owner` |
| Load | 550,759 rows in 6.2 s; all 8 row counts match |
| Required checks (null counts, midnight estimate) | 6 of 6 pass |
| PRD figure checks | All match after correcting 57 → 51 (see below) |
| `pytest` | 19 passed (10 secret-scanner unit, 3 profile unit, 6 integration) |
| Integration: idempotency | Two loads give identical counts, `sum(price)` 13,591,643.70, and review surrogate keys |
| Integration: corrupted price value | Load fails naming the table and type; database unchanged |
| Integration: wrong header / missing file | Rejected before any change |
| `ruff check .` | Passed |
| Secret scan, all files | Passed (32 files) |

**Issues found and fixed**
- PRD/technical design said 57 small sellers have a 100% late rate; that is the timestamp-based count. Under the project's date-based definition it is 51. Corrected (docs v1.2).
- `check_counts.py` initially compared PostgreSQL `Decimal` values exactly against rounded figures, reporting 9 false differences. Fixed (values normalised before comparison) with a regression test.

**Known issues / decisions**
- Raw tables intentionally have no foreign keys; orphan counts are measured instead (all 0).
- 775 orders have no items; 1 order has no payment row. To be handled in the M2 views.
- Integration tests reload the development database (safe: the load is idempotent and atomic) and take about 50 s.

**API cost incurred:** $0.00

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
1. Owner approves the M1 commit.
2. M2: remaining four roles and grants, glossary, six `analytics` views, permission tests (SC-01), PostgreSQL behaviour findings (Q-03), numeric acceptance tests, mini fixture for CI.
3. M0b (any time before M5): owner creates a DeepSeek key in `.env`; calibration of about 10 calls (< $0.01) after approval.
