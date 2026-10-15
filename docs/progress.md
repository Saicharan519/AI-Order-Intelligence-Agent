# Progress log

## Current milestone

**M4 complete. LLM provider changed to the Gemini API free tier.** Next: M0b (Gemini key from the owner; free-tier limits recorded; about 10 calibration calls after approval), then M5.

## 2026-10-15 — Provider change: DeepSeek to Gemini (free tier)

**Why:** the DeepSeek top-up could not be paid with the owner's card. The owner chose the free Gemini API.

**Verified from Google's official documentation (2026-10-15):** OpenAI-compatible endpoint (beta), so the planned `openai` SDK client still works; `gemini-3.5-flash-lite` and `gemini-3.8-flash` are stable, free-tier models recommended for new projects; thinking cannot be switched off on Gemini 3 models and its tokens count toward each call's output limit; free-tier rate limits are visible only in Google AI Studio; free-tier content may be used to improve Google's products.

**Documents changed:** PRD v1.4 (section 13 rewritten; G5, F-09, F-11, F-16, FR-16, FR-18, FR-20, NFR-02, NFR-05, SC-09, A-03, A-05, R-05, R-07, R-10, Q-02), technical design v1.5 (section 10 rewritten; principle 6, diagram, stack, threat T6, usage endpoint, Q-02), implementation plan v1.3, `.env.example` (Gemini settings and quota caps). The local `.env` was updated with empty Gemini entries (no values printed).

**Unchanged:** architecture, database, validator, executor, evaluation design. Only the LLM provider, the cost model ($2 budget → $0 with quota caps and a notional cost report), and output limits (room for thinking tokens) change.

**API cost incurred:** $0.00

## 2026-10-15 — M4: validator and guarded executor

**Completed**
- `scripts/gen_allowlists.py` → `src/orderintel/guard/allowlist.json` (6 views, 62 columns, types and comments, introspected as `oi_agent`) with a drift test.
- `src/orderintel/guard/validator.py`: VR-01 to VR-09 with sqlglot; whole-tree checks (catches `DELETE` inside a CTE); schema-aware column resolution on a copy; LIMIT 501 enforcement; SQL regenerated without comments; pglast second opinion. Returns `ValidatedSQL`, which only the validator can create.
- `src/orderintel/db/executor.py`: read-only transaction, `SET LOCAL statement_timeout` and `search_path`, EXPLAIN cost ceiling (250,000), fetch 501 rows and flag truncation at 500, client-side cancel timer, sanitised errors.
- `docs/parser_decision.md` (Q-04): sqlglot primary, pglast second opinion.
- Playbook-SQL test scaffold (skipped until M7).

**Tests and checks (actually run)**

| Check | Result |
|---|---|
| Validator unit tests (positive and negative per rule, 26 legitimate view queries, 18 PostgreSQL function spellings, forged `ValidatedSQL`) | 134 passed |
| Executor integration tests (26 queries run; shape; row cap; cost ceiling; server timeout; client-side cancel with the server timeout disabled; read-only even with a forged DELETE; error sanitising) | passed |
| Deterministic attack suite: 28 SQL attacks from `attacks.yaml` | 28 of 28 stopped by the expected layer: 24 validator, 2 cost ceiling, 2 row cap; 0 ran unrestricted |
| Allow-list drift test | passed |
| Q-04 parser comparison (66 inputs incl. nested comments, dollar quoting, escape strings) | 0 accepted queries read by PostgreSQL as anything but one SELECT |
| Full `pytest` | 415 passed, 1 skipped (playbook scaffold) |
| `ruff check .`, `pip check` | passed |

**Issues found and fixed during M4**
- sqlglot represents `AND`, `OR`, `EXISTS`, and `ARRAY[...]` as function nodes, so the first validator version rejected ordinary `WHERE a AND b`; 7 of 26 legitimate queries failed. Fixed; `ARRAY[...]` is size-limited like `IN` lists.
- `FOR UPDATE` was rejected under VR-02 instead of VR-03 (sqlglot's `Lock` node); relabelled.
- The cost-ceiling value was first written before measuring; replaced with the calibrated 250,000 and the measurements recorded.

**Known limitations**
- Backslashes in ordinary string literals may be reinterpreted by sqlglot (`'\x41'` → `'A'`); structure is unaffected.
- Regex operators (`~`) are rejected; `LIKE`/`ILIKE` work.
- A query that returns rows from an expensive join is estimated cheaply because of the injected LIMIT; the 8 s timeout is the guard for those.
- The EXPLAIN ceiling is calibrated on hand-written queries; M5 re-tunes it on model-written SQL.

**API cost incurred:** $0.00
 M0b (DeepSeek calibration, paid) waits for an API key and explicit approval.

## 2026-10-15 — M3: golden set and evaluation harness

**Completed**
- `eval/golden/questions.yaml`: 60 questions (lookup 8, aggregate 14, trend 12, trap 14, ambiguous 6, out-of-scope 6), 40 dev / 20 test, every category in the test split. References on raw tables; 6 accepted alternatives for legitimately different answers or shapes. Trap questions chosen only where the naive answer differs measurably (e.g. Nov 2017 revenue 1,003,862 vs 1,172,639 from payments).
- `src/orderintel/evaluation/compare.py`: execution-accuracy comparer (exact counts; display-rounding tolerance 0.051 or 0.01% relative; names and column order ignored; multiset or ordered rows; extra columns opt-in).
- `src/orderintel/evaluation/golden.py`: schema validation (pydantic), loader, test-split fingerprint.
- `eval/run_eval.py --refs-only`: validates structure and runs all references as read-only `oi_eval`; writes `eval/golden/REVIEW.md` for the owner's review; `--freeze` records the fingerprint.
- `eval/crosscheck.py`: 27 references re-implemented in pandas.
- Drafts: `eval/golden/attacks.yaml` (40 cases in 7 categories) and `eval/golden/investigation.yaml` (15 cases + 2 planted anomalies; labels marked "to label" are completed by independent analysis before M7 narration runs).

**Tests and checks (actually run)**

| Check | Result |
|---|---|
| Golden structure (category and split counts) | Pass |
| 66 reference queries (60 items incl. alternatives) as `oi_eval` | All run, non-empty, non-trivial, < 2 s |
| pandas cross-check | 27 of 27 agree |
| Negative controls: four known-wrong trap answers | 4 of 4 rejected (incl. a 0.94% fan-out error) |
| Comparer unit tests | 17 passed |
| Golden-schema unit tests (tamper detection: any test-item edit changes the fingerprint) | 5 passed |
| Full `pytest` after freeze | 216 passed, 0 skipped |
| `ruff check .` | Pass |

**Decisions**
- The test split was frozen only after the owner's review (freezing first would make the review meaningless). Fingerprint: `c8262a280a0dc64fe5ab292784fd20785df4a9d03caa75d72c84a05fbbe62a6a` in `eval/golden/test_split.sha256`.
- Library code lives in `src/orderintel/evaluation/` (importable, tested); `eval/` holds data files and CLI scripts.
- Booleans are not equal to labels: a model answering "late"/"on time" where the reference returns true/false fails. Known strictness; reported per failure tag in M5.

**API cost incurred:** $0.00

## 2026-10-15 — M2: roles and the semantic layer

**Completed**
- Roles `oi_agent`, `oi_trace`, `oi_eval`, `oi_injtest` (plus `oi_owner`): no superuser/createdb/createrole/bypassrls/replication; separate passwords; connection limits; role defaults (agent: 8 s timeout, read-only, `search_path=analytics`, 256 MB temp files). PUBLIC database and `public` schema privileges revoked.
- `glossary/glossary.md` from PRD section 6, with where each definition is implemented.
- Migration `002_analytics_views.sql`: six views (`orders`, `order_items`, `payments`, `reviews`, `sellers`, `data_coverage`) with database comments; grants to `oi_agent` and `oi_eval`.
- Migration `003_trace_schema.sql`: `trace.requests`, `trace.steps`, `trace.spend`; grants to `oi_trace` only.
- Permission suite: 38 must-fail statements run in two modes (role defaults; read-only switched off) plus catalog, column, and other-role checks.
- Q-03 resolved: `docs/postgres_findings.md` and `tests/integration/test_postgres_findings.py`.
- Numeric acceptance through the views as `oi_agent`.

**Files created:** `db/migrations/002_analytics_views.sql`, `db/migrations/003_trace_schema.sql`, `glossary/glossary.md`, `docs/postgres_findings.md`, `tests/integration/{agent_attacks,test_permissions,test_postgres_findings,test_semantic_layer}.py`.
**Files modified:** `scripts/migrate.py` (all roles), `src/orderintel/config.py`, `src/orderintel/db/connect.py` (per-role connections), `scripts/check_counts.py` (LF output), `README.md`, `docs/PRD.md` v1.3, `docs/TECHNICAL_DESIGN.md` v1.3, `docs/IMPLEMENTATION_PLAN.md` v1.2, `docs/data_profile.md` (regenerated).

**Tests and checks (actually run)**

| Check | Result |
|---|---|
| Full `pytest` | 132 passed |
| SC-01: 38 attack statements as `oi_agent`, role defaults | 38 of 38 fail |
| SC-01: same, read-only switched off by the session | 38 of 38 fail with 42501 (permission) |
| Agent can read each view; sees exactly six relations; no review text column | Passed |
| `oi_trace` cannot read business data; `oi_eval` cannot write or read traces | Passed |
| Q-03 behaviours (11 tests) | All five design assumptions confirmed |
| PRD Example 1 (top 5 categories 2017) via views | Exact match (revenue, share, orders) |
| PRD Example 2 (20 monthly late rates) via views | Exact match |
| PRD Example 3 headline (1,328 of 7,003) | Exact match |
| Views reproduce M1 raw figures (96,470 delivered, 6,534 late, 13,591,643.70 revenue, no fan-out, 6,108,492.27 for 2017, 96,096 people, 1,278 multi-seller) | Passed |
| `ruff check .` and secret scan | Passed |

**Key findings**
- With role defaults, 15 attacks were blocked only by read-only mode; the agent can switch read-only off and its timeout off via `set_config` in a `SELECT`. Grants are the real wall; the validator and executor (M4) must add the rest.
- The agent can see raw table and column names in the catalogs (not data).

**Design deviations (recorded in docs v1.3)**
- Untranslated categories keep their Portuguese names instead of `unknown`.
- Negative stage durations (166 handling, 23 transit) are NULL.
- `data_coverage` includes the empty month 2016-11 and flags it partial.
- Mini fixture deferred to M7/M10.

**API cost incurred:** $0.00

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
1. Owner approves the M4 commit (and push).
2. M0b: owner adds the DeepSeek key to `.env`; provider facts checked (Q-02); about 10 calibration calls (< $0.01) after approval.
3. M5: LLM client with budget guard and cache; SQL-generation prompts A–C; cost estimate and approval before each paid run.
3. M0b (any time before M5): owner creates a DeepSeek key in `.env`; calibration of about 10 calls (< $0.01) after approval.
