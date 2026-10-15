# Order Intelligence Agent

A natural-language analytics assistant over the Olist Brazilian e-commerce dataset. It answers questions with validated, read-only SQL, shows the evidence behind every number, and is measured with a golden question set, ablations, and a safety suite, within a US$2 LLM budget.

> **Status:** milestone M3 (golden question set and scoring harness). The agent itself is not built yet. See [docs/progress.md](docs/progress.md).

Design documents: [PRD](docs/PRD.md) · [Technical design](docs/TECHNICAL_DESIGN.md) · [Implementation plan](docs/IMPLEMENTATION_PLAN.md)

## Prerequisites

- Python 3.11 or later
- Docker Desktop (running) with Docker Compose
- git

## Setup

Run from the project root (the folder containing this README), in Git Bash.

1. Create the environment file and fill in the values:
   ```bash
   cp .env.example .env
   ```
   Give every `*_PASSWORD` a different random value. Leave `DEEPSEEK_API_KEY` empty until milestone M0b. Never commit `.env`.
2. Create the virtual environment and install pinned dependencies:
   ```bash
   python -m venv .venv
   .venv/Scripts/python -m pip install -r requirements-dev.txt
   .venv/Scripts/python -m pip install -e . --no-deps
   ```
   (On macOS/Linux use `.venv/bin/python`.)
3. Enable the secret-check pre-commit hook:
   ```bash
   git config core.hooksPath .githooks
   ```
4. Start the database:
   ```bash
   docker compose up -d db
   ```
   Check it is healthy (`STATUS` shows `(healthy)`):
   ```bash
   docker compose ps
   ```

5. Download the dataset: from https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce (Kaggle login required), extract the 9 CSV files directly into `data/raw/` (licence: CC BY-NC-SA 4.0; see [docs/data_notes.md](docs/data_notes.md) for file checksums).
6. Create the tables and load the data:
   ```bash
   .venv/Scripts/python scripts/migrate.py
   .venv/Scripts/python scripts/load_data.py
   .venv/Scripts/python scripts/check_counts.py
   ```
   Expected: `migrate.py` prints five roles (`oi_owner`, `oi_agent`, `oi_trace`, `oi_eval`, `oi_injtest`) and applies three migrations (raw tables, analytics views, trace tables); the loader prints eight tables with `ok` and `Loaded 550,759 rows`; the checker ends with `required checks failed: 0; PRD figures differing: 0`. All three are safe to re-run: migrations skip what is already applied and reset role passwords and limits from `.env`, and the loader replaces the data atomically.

## Database layout

| Schema | Contents | Who can read it |
|---|---|---|
| `raw` | Typed copies of the eight source CSVs | `oi_owner`, `oi_eval` |
| `analytics` | Six curated views with the business definitions applied ([glossary](glossary/glossary.md)) | `oi_agent`, `oi_eval` |
| `trace` | Request traces and the LLM spend ledger | `oi_trace` |
| `meta` | Applied migrations | `oi_owner` |

`oi_agent`, the only role that will run model-written SQL, can read the six views and nothing else; 38 attack statements are tested to fail by permissions alone. See [docs/postgres_findings.md](docs/postgres_findings.md).

Stop the database with `docker compose stop db`. `docker compose down` removes the container but keeps the data volume; `docker compose down -v` also deletes the data.

## Tests and checks

```bash
.venv/Scripts/python -m pytest
.venv/Scripts/python -m ruff check .
.venv/Scripts/python scripts/check_secrets.py --all
```

Evaluation harness (no LLM, no cost):

```bash
.venv/Scripts/python eval/run_eval.py --refs-only --review eval/golden/REVIEW.md
.venv/Scripts/python eval/crosscheck.py
```

Expected: `All references valid.` and `27 of 27 references agree with the pandas implementation`.

Paid LLM tests are marked `paid` and never run by default. Integration tests (marked `integration`) need the running database and the CSVs; they are skipped automatically otherwise. Run only fast unit tests with `-m "not integration"`.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `failed to connect to the docker API ... dockerDesktopLinuxEngine` | Docker Desktop is not running. Start it and wait until it says "Engine running". |
| `set POSTGRES_PASSWORD in .env` | `.env` is missing or the value is empty. See step 1. |
| Port 5432 already in use | Another PostgreSQL is running. Set `POSTGRES_PORT=5433` in `.env`. |
| `Permission denied` inside `.venv` | OneDrive sync can lock files. Pause sync or recreate the venv outside the project folder. |
| `LOAD FAILED ... missing files` | A CSV is not directly in `data/raw/` (often extracted into a subfolder). Move the 9 files up one level. |
| `LOAD FAILED ... row counts do not match` | The CSV differs from the expected version. Compare checksums with `docs/data_notes.md`. Nothing was changed in the database. |
| `password authentication failed for user "oi_owner"` | `.env` password changed after roles were created. Re-run `scripts/migrate.py`, which resets role passwords from `.env`. |
| Secret check fails | It names the file, line, and rule (never the value). Move the secret into `.env`. If it was ever committed, rotate it. |

## Security notes

- Secrets live only in `.env` (git-ignored). `.env.example` lists names only.
- The database port is bound to `127.0.0.1` and is never exposed to the network.
- A pre-commit hook and `scripts/check_secrets.py` block committing `.env`, the raw dataset, key-shaped strings, and any value present in your local `.env`.
