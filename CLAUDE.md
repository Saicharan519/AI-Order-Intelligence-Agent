# CLAUDE.md

Guidance for AI coding sessions in this repository. The source of truth for scope and design is `docs/` (PRD, technical design, implementation plan); `docs/progress.md` records every milestone with costs and measured results.

## Commands (Git Bash on Windows, from the project root)

```bash
.venv/Scripts/python -m pytest -q                      # full suite; needs the Docker database (expected: all pass with the real data)
.venv/Scripts/python -m pytest -q -m "not integration" # unit tests only, no database
.venv/Scripts/python -m ruff check .                   # lint (enforced in CI)
.venv/Scripts/python scripts/check_secrets.py --all    # secret scan (also the pre-commit hook and CI)
.venv/Scripts/python -m uvicorn orderintel.api.app:app --host 127.0.0.1 --port 8000
.venv/Scripts/python -m streamlit run src/orderintel/ui/app.py -- --local   # simple fallback UI
```

Web app (Next.js 16, from `web/`): `npm run dev` (real API; sign in, invite-only accounts; first admin via `scripts/create_admin.py`, which prompts for the password), `npm run dev:mock` (recorded answers, no backend, $0), and the CI checks `npm run lint`, `npm run typecheck`, `npm test`, `npm run build`. Next.js 16 differs from older versions: read `web/node_modules/next/dist/docs/` before changing framework-level code (see `web/AGENTS.md`).

Database: `docker compose up -d db` (container `orderintel-db-1`, port 5432). Schema changes go in a NEW file in `db/migrations/` (applied files are checksummed; editing one is an error), then `scripts/migrate.py`; after changing views, run `scripts/gen_allowlists.py`.

## Rules that protect the budget and the data

- **No paid model call without the owner's explicit approval.** Paid scripts print an estimate with `--estimate` and refuse without `--approved`; tests marked `paid` never run by default. Prefer off-peak hours (DeepSeek peak: 01–04 and 06–10 UTC on weekdays). Total cap $1.90, daily $0.40, enforced in `src/orderintel/llm/budget.py`.
- Test fakes that write to the real ledger must use the Gemini fake config (billed at $0), tag rows `test:...`, and delete them with a prefix match (`config_name LIKE 'test:x%'`: the agent appends `:D`).
- The frozen test split (`eval/golden/test_split.sha256`) must not be edited. Repeated runs need `--confirm-test` and a `--run-tag` so they never overwrite the M5 headline file.
- Never read, print, or ask for secrets (`.env`). Compare secret values in memory only and report setting names, never values.
- `scripts/build_mini_db.py` only drops databases ending in `_mini` or `_ci`. Never drop or reload the real `orderintel` database without approval. A second copy of the repo on the same machine must set `COMPOSE_PROJECT_NAME`, or Docker Compose reuses the real container.

## Architecture invariants (do not weaken)

- Model-written SQL reaches the database only as `ValidatedSQL` (minted by `guard/validator.py`) through `db/executor.py`, as role `oi_agent` (SELECT on the six analytics views only). Prompts are not a security boundary.
- Every number in an answer or narration must be traced by `agent/grounding.py`; findings are computed in code, the model only narrates.
- Glossary rules that matter for correctness are enforced in code, not only in prompts: `guard/business_rules.py` (revenue counts sales only) runs on validated SQL and feeds the repair loop.
- `agent/precheck.py` answers questions about the data, out-of-range periods, and why-questions about months outside the analysis window in code before the router; "sparse" means outside the window, never a fixed order count (the synthetic CI data has about 400 orders in every month).
- `src/orderintel/safety/` is test-only; no product module may import it (a test enforces this).
- Traces and logs pass through `orderintel/redact.py`.
- The browser never calls FastAPI directly: `web/src/lib/server/` forwards an allow-list of endpoints with only the JSON body and the session from the httpOnly `oi_session` cookie (as `Authorization: Bearer`); the token is never returned to the browser, and every POST must pass the same-origin check (tests in `web/src/test/proxy.test.ts`).
- Accounts (`src/orderintel/auth/`, schema `app`, written as `oi_trace`; `oi_agent` has no access): scrypt password hashes, tokens and invite codes stored only as SHA-256 hashes, invite-only sign-up. Every history, trace and spend query is scoped to the caller's user id (NULL for the `X-Access-Code` operator key); `tests/integration/test_accounts.py` proves one user cannot see another's conversations. Never create real accounts or set real passwords for the owner; test accounts use the domain `accounts.test` and are deleted.

## Tests

- `realdata` marks tests that check real Olist figures; they skip with a reason on the synthetic fixture (CI runs `scripts/build_mini_db.py --db orderintel_ci`).
- Assertions about "nothing changed" compare before and after, never a hard-coded real count.

## Conventions

- One commit per milestone or request; the subject is one plain sentence (no milestone prefix, no trailer). Commit and push only with the owner's approval.
- Format only the files you changed (`ruff format <files>`); eight older files are not formatter-clean and are left as they are.
- Report results as measured, including failures, and update `docs/progress.md`.
