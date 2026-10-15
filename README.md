# Order Intelligence Agent

A natural-language analytics assistant over the Olist Brazilian e-commerce dataset. It answers questions with validated, read-only SQL, shows the evidence behind every number, and is measured with a golden question set, ablations, and a safety suite, within a US$2 LLM budget.

> **Status:** milestone M0a (local setup). The agent itself is not built yet. See [docs/progress.md](docs/progress.md).

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

Stop the database with `docker compose stop db`. `docker compose down` removes the container but keeps the data volume; `docker compose down -v` also deletes the data.

## Tests and checks

```bash
.venv/Scripts/python -m pytest
.venv/Scripts/python -m ruff check .
.venv/Scripts/python scripts/check_secrets.py --all
```

Paid LLM tests are marked `paid` and never run by default.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `failed to connect to the docker API ... dockerDesktopLinuxEngine` | Docker Desktop is not running. Start it and wait until it says "Engine running". |
| `set POSTGRES_PASSWORD in .env` | `.env` is missing or the value is empty. See step 1. |
| Port 5432 already in use | Another PostgreSQL is running. Set `POSTGRES_PORT=5433` in `.env`. |
| `Permission denied` inside `.venv` | OneDrive sync can lock files. Pause sync or recreate the venv outside the project folder. |
| Secret check fails | It names the file, line, and rule (never the value). Move the secret into `.env`. If it was ever committed, rotate it. |

## Security notes

- Secrets live only in `.env` (git-ignored). `.env.example` lists names only.
- The database port is bound to `127.0.0.1` and is never exposed to the network.
- A pre-commit hook and `scripts/check_secrets.py` block committing `.env`, the raw dataset, key-shaped strings, and any value present in your local `.env`.
