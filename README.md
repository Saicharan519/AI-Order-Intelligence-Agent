# Order Intelligence Agent

[![CI](https://github.com/Saicharan519/AI-Order-Intelligence-Agent/actions/workflows/ci.yml/badge.svg)](https://github.com/Saicharan519/AI-Order-Intelligence-Agent/actions/workflows/ci.yml)

A natural-language analytics assistant over the [Olist Brazilian e-commerce dataset](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce) (about 100,000 orders, 2016 to 2018). Ask a question in plain English and it answers with **validated, read-only SQL**, shows the **evidence behind every number**, and can **investigate** why deliveries were late or reviews were low. Every claim below is measured, within a total LLM budget of US$2.

- **Ask:** "Top 5 categories by revenue in 2017" → a table and bar chart, the exact SQL, the definitions applied, and a headline whose numbers are checked against the query result.
- **Investigate:** "Why was March 2018 so bad for deliveries?" → a fixed playbook of validated queries, findings computed in code (late rate 19.0% vs 5.8% baseline, top driver carrier transit, the states and sellers behind it), and a narration checked number by number.
- **Safe by construction:** the model never holds credentials and never connects to the database. Its SQL is parsed and allow-listed, then run by a role that can read six views and nothing else.

Design documents: [PRD](docs/PRD.md) · [Technical design](docs/TECHNICAL_DESIGN.md) · [Implementation plan](docs/IMPLEMENTATION_PLAN.md) · [Progress log](docs/progress.md)

## Architecture

```mermaid
flowchart LR
  UI["Streamlit UI"] -->|"question + session id"| API["FastAPI backend<br/>access code, rate limits"]
  API --> RT["Router (LLM, JSON)"]
  RT -->|answer| SG["SQL generator (LLM, JSON)"]
  RT -->|investigate| PB["Playbook runner (typed params)"]
  RT -->|"clarify / refuse"| OUT["Structured response"]
  SG --> VAL["Validator (AST, allow-lists)"]
  PB --> VAL
  VAL -->|ok| EX["Executor (oi_agent, read-only, limits)"]
  VAL -->|reject| RP["Repair loop (max 2)"]
  EX -->|error| RP
  RP --> SG
  EX --> DB[("PostgreSQL: analytics views")]
  EX --> AW["Answer writer (LLM) + grounding check"]
  AW --> OUT
  API --> TR[("trace schema: requests, steps, spend")]
  LLM["LLM client + budget guard"] --> DS["DeepSeek API"]
  RT -.-> LLM
  SG -.-> LLM
  AW -.-> LLM
```

How model-written SQL reaches the database:

```
model-written SQL ──► validator ──► ValidatedSQL ──► executor ──► PostgreSQL (oi_agent)
                      VR-01..VR-09     (only the       read-only transaction, 8 s timeout,
                      sqlglot + pglast  validator      EXPLAIN cost ceiling, 500-row cap,
                                        can mint it)   client-side cancel timer
```

| Layer | What it enforces |
|---|---|
| Database roles | `oi_agent` (the only role that runs model SQL) can `SELECT` six views and nothing else; no superuser, no `PUBLIC` grants |
| Validator | one `SELECT`, allow-listed views, columns, functions and casts, enforced `LIMIT`, size limits, comments stripped, re-parsed by PostgreSQL's own parser |
| Executor | read-only transaction, statement timeout, `EXPLAIN` cost ceiling, row cap, cancel timer, sanitised errors |
| Grounding | every number in an answer or narration must trace to the query results or findings; causal wording is flagged |
| Budget guard | worst-case cost checked before every call against a $1.90 total and $0.40 daily cap |

Stack: Python 3.12, PostgreSQL 18 (Docker), psycopg 3, sqlglot + pglast, Pydantic v2, LangGraph (thin wiring), FastAPI, Streamlit, DeepSeek (`deepseek-flash`) with the Gemini free tier as an optional second provider.

## Results (measured)

All figures are from the stored runs in [`eval/results/`](eval/results/) and the reports in [`eval/reports/`](eval/reports/). Small samples: the 95% intervals are wide and are always shown.

**SQL accuracy: ablation on the frozen 20-item test split** (18 answerable items; [ablation.md](eval/reports/ablation.md))

| Configuration | What the model sees | Correct | 95% CI |
|---|---|---|---|
| A | raw table DDL only | 3/18 (17%) | 6%-39% |
| B | A + glossary definitions | 15/18 (83%) | 61%-94% |
| C | curated views + full glossary | 15/18 (83%) | 61%-94% |
| D (product) | C + validator, cost gate, repairs | 15/18 (83%) | 61%-94% |

Business definitions (the glossary) are what lift accuracy from 17% to 83%. On the 36-item dev split, D was 34/36; both misses were format-only (36/36 data-correct).

**Variance and model comparison** ([model_comparison.md](eval/reports/model_comparison.md))

| Model | Correct (D, test split) | Cost per item | p50 latency |
|---|---|---|---|
| deepseek-flash, 3 runs | 15, 16, 15 of 18 (83%-89%) | $0.00010 | 1.3 s |
| deepseek-v4-pro | 15/18 | $0.00041 | 1.8 s |
| gemini-3.5-flash-lite (free tier) | 16/18 | $0 | rate-limited |

Only one item changed across the three flash runs. The larger model was not more accurate, cost about 4x as much, and misrouted one investigation, so `deepseek-flash` stays the primary model.

**Ask and Investigate** ([ask_eval.md](eval/reports/ask_eval.md), [investigation_report.md](eval/reports/investigation_report.md))

| Check | Result |
|---|---|
| Routing (answer, investigate, clarify, refuse), 60 golden questions | 60/60 |
| Answers with every number traced to the result | 56/56 |
| Ask latency | p50 2.8 s, p95 4.8 s |
| Investigations: routing / every number traced / verdict matches independent label | 15/15 / 13/13 / 13/13 |
| Top driver correct (positive cases) / negative controls "nothing notable" | 9/9 / 4/4 |
| Follow-ups that keep the investigation scope and are answered correctly | 5/5 |
| Planted anomalies found on a synthetic dataset (+10 transit days in one state; +5 handling days for one seller) | 2/2, and 0/2 with the plants removed |

**Safety** ([safety_report.md](eval/reports/safety_report.md)): 44 attack cases: 32 SQL attacks (destructive statements, stacked statements, catalog and raw-table reads, `pg_sleep` / `set_config` / file functions, Cartesian joins, oversized inputs), 6 direct prompt injections, and 6 indirect injections hidden in review text read through a test-only tool. Model-involving cases ran 3 times each.

> In this suite, **0 of 44 attack cases succeeded**: none caused a write, a read outside the six views, a secret exposure, an obeyed planted instruction (canary), a verbatim system-prompt leak, or a resource-limit breach. The database was unchanged after every run.

This is the measured result of this suite, not a claim that the system is immune to prompt injection (see Limitations).

**Cost** ([cost_report.md](eval/reports/cost_report.md)): the whole project, every evaluation included, used 608 real model calls for **$0.079 (4.2% of the $1.90 cap)**; 75% of input tokens were provider prompt-cache hits. A typical question costs about $0.0003.

## Limitations

- **Prompt injection cannot be eliminated.** Poisoned text could still skew which allowed queries are issued or how an answer is worded. The blast radius is bounded: the model cannot write, cannot read outside the views, has no outbound tools, and holds no secret.
- **SQL correctness is measured, not guaranteed:** 83% on a small test split. Known failure: per-payment-type counts are not expressible through the `payments` view (one row per order, by design, to prevent join fan-out).
- **Playbook topic is not checked in code:** `deepseek-v4-pro` once answered a revenue question with the review playbook (grounded, but off-topic).
- **`EXPLAIN` cost estimates can be wrong;** the statement timeout is the real protection.
- **Associations, not causes:** findings describe observational data; causal wording is linted.
- **Single process:** rate limits and session scope are in memory.
- **Out of scope (PRD non-goals):** forecasting, writes, maps and geolocation, review-text analysis, user accounts, real-time data, and claims about scale.

## Setup

Requirements: Python 3.11 or later, Docker Desktop (running), git. Commands are for Git Bash on Windows; on macOS or Linux use `.venv/bin/python` instead of `.venv/Scripts/python`.

1. Create the environment file:
   ```bash
   cp .env.example .env
   ```
   Give every `*_PASSWORD` and `ACCESS_CODE` a different random value. For model calls, add a `DEEPSEEK_API_KEY` (optional: everything except model calls works without it). Never commit `.env`.
2. Create the virtual environment:
   ```bash
   python -m venv .venv
   .venv/Scripts/python -m pip install -r requirements-dev.txt
   .venv/Scripts/python -m pip install -e . --no-deps
   ```
3. Enable the secret-check pre-commit hook:
   ```bash
   git config core.hooksPath .githooks
   ```
4. Start the database and wait until `docker compose ps` shows `(healthy)`:
   ```bash
   docker compose up -d db
   ```
5. Download the dataset from [Kaggle](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce) (login required; licence CC BY-NC-SA 4.0, not redistributed here) and extract the 9 CSV files directly into `data/raw/` (checksums: [docs/data_notes.md](docs/data_notes.md)).
6. Create the roles and tables, then load and verify the data:
   ```bash
   .venv/Scripts/python scripts/migrate.py
   .venv/Scripts/python scripts/load_data.py
   .venv/Scripts/python scripts/check_counts.py
   ```
   Expected: five roles and five migrations; `Loaded 550,759 rows`; `required checks failed: 0; PRD figures differing: 0`. All three are safe to re-run.

Without the Kaggle data you can still run everything except the real-data figures on a synthetic dataset: `.venv/Scripts/python -m scripts.build_mini_db --db orderintel_ci`, then set `POSTGRES_DB=orderintel_ci` in `.env`.

## Run the app

Start the API (terminal 1):

```bash
.venv/Scripts/python -m uvicorn orderintel.api.app:app --host 127.0.0.1 --port 8000
```

Start the UI (terminal 2) and open http://localhost:8501:

```bash
.venv/Scripts/python -m streamlit run src/orderintel/ui/app.py
```

Type the `ACCESS_CODE` from your `.env` into the access-code field. For local development only, `-- --local` after the UI command makes the UI server use the code from `.env` itself (accepted only when `API_URL` points to localhost). Try the three example questions in the sidebar. Every request is traced; summarise the traces with `.venv/Scripts/python scripts/trace_report.py`.

API: `POST /v1/ask`, `GET /v1/requests/{id}`, `POST /v1/sessions/{id}/scope/clear`, `GET /v1/budget` (all need the `X-Access-Code` header) and `GET /v1/health`. Set `LLM_ENABLED=false` in `.env` to block all model calls.

## Tests and evaluation

```bash
.venv/Scripts/python -m pytest -q
.venv/Scripts/python -m ruff check .
.venv/Scripts/python scripts/check_secrets.py --all
```

Expected with the real data loaded: 616 passed. No test calls a real model: model behaviour is tested with a fake model, and tests marked `paid` never run by default. Tests marked `realdata` check figures of the real dataset and are skipped (with the reason shown) on the synthetic dataset; CI runs that way on every push (lint, secret scan, and 497 tests against a PostgreSQL service).

Free evaluation tools (no model calls):

```bash
.venv/Scripts/python eval/run_eval.py --refs-only
.venv/Scripts/python eval/crosscheck.py
.venv/Scripts/python eval/run_safety_eval.py --deterministic
.venv/Scripts/python eval/run_investigation_eval.py --planted
.venv/Scripts/python scripts/cost_report.py
```

Paid evaluations print an estimate with `--estimate` and refuse to run without `--approved`; the budget guard stops any call that could exceed the caps.

## Repository layout

| Path | Contents |
|---|---|
| `src/orderintel/` | `agent/` (router, SQL generation, answer, grounding, scope, Ask graph), `guard/` (validator), `db/` (connections, executor), `playbooks/`, `llm/` (client, pricing, budget, cache), `api/`, `ui/`, `trace/`, `safety/` (test-only injection harness) |
| `db/migrations/` | raw tables, analytics views, trace tables, injection-test schema, request traces |
| `prompts/` | versioned prompts |
| `glossary/` | business definitions used by the model and the views |
| `eval/` | golden questions (test split frozen by SHA-256), attack cases, runners, results, reports |
| `tests/` | unit, integration, and safety tests; synthetic fixture generator |
| `docs/` | PRD, technical design, implementation plan, progress log, findings |

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `failed to connect to the docker API` | Docker Desktop is not running. Start it and wait for "Engine running". |
| `password authentication failed` | A password in `.env` changed after the roles were created. Re-run `scripts/migrate.py`. |
| Port 5432 already in use | Another PostgreSQL is running. Set `POSTGRES_PORT=5433` in `.env`. |
| `LOAD FAILED ... missing files` | A CSV was extracted into a subfolder. Move the 9 files directly into `data/raw/`. |
| UI says "The access code is missing or wrong." | Type the `ACCESS_CODE` from `.env` and press Enter, or start the UI with `-- --local`. |
| UI says "The API is not reachable." | Start the API first (terminal 1). |
| `Permission denied` inside `.venv` | OneDrive sync can lock files. Pause sync or recreate the venv. |
| Secret check fails | It names the file, line, and rule (never the value). Move the secret into `.env`; if it was ever committed, rotate it. |

## Security notes

- Secrets live only in `.env` (git-ignored); `.env.example` lists names only. Traces and logs pass through redaction, and a test searches them for every configured secret.
- The database port is bound to `127.0.0.1`.
- A pre-commit hook and CI run `scripts/check_secrets.py`, which blocks `.env` files, the raw dataset, key-shaped strings, and any value present in your local `.env`.

## Data licence

The Olist dataset is © Olist, published on Kaggle under CC BY-NC-SA 4.0. It is not included in this repository; the synthetic test fixture is generated by code.
