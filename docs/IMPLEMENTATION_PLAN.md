# Implementation Plan: Order Intelligence Agent

| Field | Value |
|---|---|
| Version | 1.4 |
| Date | 2026-10-15 |
| Author | Sai Charan Kukkala |
| Related documents | [PRD.md](PRD.md), [TECHNICAL_DESIGN.md](TECHNICAL_DESIGN.md) |

This plan breaks the work described in the PRD and technical design into ordered milestones. Each milestone lists its objective, tasks, tests, acceptance criteria, and deliverables. Requirement and criterion identifiers (FR-, NFR-, SC-, Q-) refer to the PRD.

## 1. Conventions

**Definition of done (every milestone)**
- All listed tests pass.
- Acceptance criteria are met and the deliverables exist in the repository.
- A progress entry is added to `docs/progress.md` (date, milestone, results, any changed decision or target, with the reason).
- No secrets are present in the working tree or git history.
- Changes are committed with a descriptive message, after the project owner has reviewed and approved the commit. Nothing is pushed, published, or deployed without explicit approval.
- No paid LLM call is made without the project owner's explicit approval and a prior cost estimate.

**Rules**
- The held-out test split is not used for tuning. It is run once per configuration in M5.
- Results are reported as measured. A changed target is recorded with its rationale in the document history.
- The agent database role is never granted extra privilege to make a test pass.

**Test levels** (see the technical design, section 12): unit, integration, deterministic safety, LLM-involving safety, evaluation, and deployment smoke tests.

## 2. Milestone overview and dependencies

```
M0 → M1 → M2 → M3 ─┐
            └─→ M4 ─┴→ M5 → M6 → M7 → M8 → M9 → M10 → M11
```

| Milestone | Outcome | Paid LLM calls |
|---|---|---|
| M0 | Environment, provider facts, measured cost per call | Calibration only |
| M1 | Data loaded with proper types | No |
| M2 | Database roles and the semantic layer | No |
| M3 | Golden set and evaluation harness | No |
| M4 | SQL validator and guarded executor | No |
| M5 | Baseline agent and ablation results | Yes |
| M6 | Complete Ask mode | Yes |
| M7 | Investigate mode | Yes |
| M8 | Safety suite | Partly |
| M9 | API, tracing, and UI | Cached only |
| M10 | Hardening, model comparison, documentation | Yes |
| M11 | Deployment and packaging | Smoke test only |

M3 and M4 both complete before M5. Safety tests are started in M3 and M4 and completed in M8.

## 3. Milestones

### M0. Environment and calibration

**Objective:** a working local environment, stored credentials, and measured LLM cost per call.

M0 runs in two parts. **M0a** (T-0.1 to T-0.3 and T-0.6) is local and free. **M0b** (T-0.4 and T-0.5) needs the API key and makes paid calls, so it starts only after explicit approval; it does not block M1 to M4.

| Task | Description | Expected outcome |
|---|---|---|
| T-0.1 | Verify the toolchain: Python 3.11 or later, git, Docker with Compose. Record versions in `docs/environment.md`. | Versions documented |
| T-0.2 | Create the repository layout (technical design, section 4), virtual environment, `.gitignore` (including `.env`, `data/raw/`, `eval/cache/`), and `.env.example` (names only). Add the three design documents under `docs/`. | Initial commit |
| T-0.3 | Write `docker-compose.yml` with PostgreSQL. Choose the pinned image tag after checking current tags; add a healthcheck; bind the database port to localhost only. | `docker compose up -d db` reports healthy |
| T-0.4 | Create the DeepSeek API key and store it only in `.env`. Record in `docs/provider_facts.md`: base URL, model identifiers, usage fields including cache hits, thinking-mode default, rate limits, balance expiry, and minimum top-up (Q-02). | Provider facts documented |
| T-0.5 | Calibration script (about 20 lines): make 10 small calls with `max_tokens` set, log token usage, and compute cost. Compare with the PRD estimates. | Measured cost per call recorded |
| T-0.6 | Secret hygiene: confirm `.env` is ignored and add a secret-pattern check to run before commits. | Check passes |

**Tests:** `.env` is untracked · the database container is healthy · one JSON-mode call succeeds · computed cost matches the provider balance change within rounding.
**Acceptance criteria:** Q-02 is answered in writing; measured per-call cost is known; the PRD cost estimates are confirmed or amended.
**Deliverables:** repository skeleton, `docs/environment.md`, `docs/provider_facts.md`.

### M1. Data load

**Objective:** the eight tables are in PostgreSQL with proper types, reproducibly.

| Task | Description | Expected outcome |
|---|---|---|
| T-1.1 | Download the Olist archive from Kaggle into `data/raw/`. Copy the licence and terms text from the Kaggle page into `docs/data_notes.md` (Q-01). | Source terms documented |
| T-1.2 | Migration creating schema `raw` and the typed tables (technical design, section 6.2). | Tables exist |
| T-1.3 | `scripts/load_data.py`: `COPY`, empty string to NULL, truncate-and-reload, row counts asserted. | Idempotent load |
| T-1.4 | `scripts/check_counts.py`: verify row and null counts. | Check passes |

**Expected counts:** orders 99,441 · order items 112,650 · payments 103,886 · reviews 99,224 · customers 99,441 · products 32,951 · sellers 3,095 · translation 71. Expected nulls: `orders.order_approved_at` 160 · `order_delivered_carrier_date` 1,783 · `order_delivered_customer_date` 2,965 · `products.product_category_name` 610 · `order_reviews.review_comment_message` 58,247.
**Tests:** counts and null counts match; running the loader twice gives identical counts.
**Acceptance criteria:** FR-19 satisfied.
**Deliverables:** migration, loader, count checker, `docs/data_notes.md`.

### M2. Roles and the semantic layer

**Objective:** the data boundary exists and the known data traps are neutralised in the schema.

| Task | Description | Expected outcome |
|---|---|---|
| T-2.1 | Migration creating the five roles with the attributes and grants in the technical design (section 6.3); revoke `PUBLIC` access; passwords from the environment. | Roles exist |
| T-2.2 | Write `glossary/glossary.md` from PRD section 6. | Glossary versioned |
| T-2.3 | Migration creating the six `analytics` views (technical design, section 6.4). | Views exist |
| T-2.4 | Permission tests: at least 25 statements as `oi_agent` that must fail (raw select, trace select, INSERT, UPDATE, DELETE, TRUNCATE, DROP, CREATE, COPY, catalog writes, role changes) and the view selects that must succeed. | Test suite |
| T-2.5 | Confirm the PostgreSQL behaviours listed in the technical design (section 7.2) by experiment as `oi_agent`: `pg_sleep` callable, `set_config` effective, catalogs readable, views readable without raw privileges. Record in `docs/postgres_findings.md` (Q-03). | Findings documented; design updated if reality differs |
| T-2.6 | Numeric acceptance queries (below). | Queries pass |

**Numeric acceptance:**
- delivered orders (status delivered with a delivery date) = 96,470; late by date = 6,534 (6.77%); late by timestamp would be 7,826 (8.11%) and is recorded only to explain the definition
- joining items to payments naively inflates item revenue by 4.54% (13,591,644 to 14,209,115); the `payments` view does not
- 2017 revenue (canceled and unavailable orders excluded) is about 6,108,492 over 44,375 orders; the top five categories match PRD Example 1
- `reviews` has one row per reviewed order (98,673); 1,278 orders involve more than one seller
- `data_coverage` flags exactly the months 2016-09, 2016-10, 2016-11 (zero orders), 2016-12, 2018-09, and 2018-10 as partial

**Tests:** all of the above, as automated integration tests on the real data. The synthetic mini fixture is built with the planted-anomaly tests (M7) and wired into CI in M10, where it is first needed.
**Acceptance criteria:** SC-01 satisfied; numeric acceptance queries pass; Q-03 resolved.
**Deliverables:** role and view migrations, glossary, permission tests, `docs/postgres_findings.md`.

### M3. Golden set and evaluation harness

**Objective:** a trusted scoring system exists before any model is evaluated.

| Task | Description | Expected outcome |
|---|---|---|
| T-3.1 | Author 60 questions in `eval/golden/questions.yaml` (technical design, section 8.1): lookup 8, aggregate 14, trend or comparison 12, trap 14, ambiguous 6, out-of-scope 6. Reference SQL is written on the raw tables. Assign 40 to development and 20 to test, balanced across categories. | Question file |
| T-3.2 | Result comparer (technical design, section 8.2) with unit tests for ordering, rounding tolerance, extra columns, NULLs, and column-order independence. | Comparer tested |
| T-3.3 | `run_eval.py --refs-only`: execute every reference; fail on empty or trivial results (except refusal items) and on queries slower than 2 s. | All references run |
| T-3.4 | Independent cross-check: re-implement at least 20 references in pandas and resolve every disagreement. | Cross-check complete |
| T-3.5 | Draft `attacks.yaml` (at least 40 cases, technical design section 8.7) and `investigation.yaml` (15 cases plus 2 planted anomalies, section 8.6). Candidate positive scopes: Nov 2017, Feb 2018, Mar 2018, RJ in Mar 2018, MG in Mar 2018. Candidate negative controls: months with a late rate near 3%, such as Jul 2017. | Case files drafted |
| T-3.6 | Freeze the golden set and record a hash of the test split. | Test split locked |

**Tests:** comparer unit tests pass · all references execute · the pandas cross-check agrees on at least 20 items.
**Acceptance criteria:** golden set frozen; the trap list in PRD section 11 is fully covered; harness ready (FR-17 groundwork).
**Deliverables:** `eval/golden/*.yaml`, comparer, `run_eval.py`, cross-check notebook or script.

### M4. Validator and executor

**Objective:** the only path to the database is guarded and tested.

| Task | Description | Expected outcome |
|---|---|---|
| T-4.1 | Generate allow-lists (views and columns) by introspecting the database; commit the generated file and add a drift test. | Allow-lists generated |
| T-4.2 | Implement VR-01 to VR-09 (technical design, section 7.2) with `sqlglot`; execute the regenerated SQL, never the original string. | Validator implemented |
| T-4.3 | Executor (technical design, section 7.3): read-only transaction, timeout, `EXPLAIN` gate (generous initial ceilings, tuned in M5), row cap of 500, client-side cancel timer. | Executor implemented |
| T-4.4 | Unit tests: at least 30 attack strings (DDL, multiple statements, `COPY`, `SELECT INTO`, `pg_sleep`, `set_config`, catalogs, `generate_series`, unknown functions, columns and tables, comment tricks, large `IN` lists, Cartesian joins) plus positive tests for every construct the golden references need. | Test suite |
| T-4.5 | Compare `sqlglot` with `pglast` on the attack list and record the decision (Q-04). | Parser decision documented |
| T-4.6 | Test scaffold asserting that every playbook SQL step passes the validator (populated in M7). | Scaffold in place |

**Tests:** all of the above. An expensive-but-allowed query (a self-join of `order_items`) is stopped by the `EXPLAIN` gate or the timeout.
**Acceptance criteria:** SC-03; FR-04 and FR-05 satisfied; no attack string reaches execution.
**Deliverables:** validator, executor, allow-lists, attack tests, parser decision note.

### M5. Baseline agent and ablations

**Objective:** the first measured results, with an explicit review checkpoint.

| Task | Description | Expected outcome |
|---|---|---|
| T-5.1 | `LLMClient` with pricing, budget guard, cache, dry-run mode, and usage-to-cost conversion; unit tests for the guard using a fake model. | Client tested |
| T-5.2 | SQL-generation prompts v1: A (raw DDL), B (plus glossary), C (views plus glossary), with a static prefix first for caching. | Prompts versioned |
| T-5.3 | Run A, B, and C on the development split. Tag every failure (technical design, section 8.2). Iterate prompts at most three times, each recorded as a prompt version; tune on the development split only. | Dev results and failure tags |
| T-5.4 | Build configuration D (validator, `EXPLAIN` gate, up to two repairs) and tune the `EXPLAIN` ceilings from real queries. | Config D working |
| T-5.5 | Run A, B, C, and D once on the test split (and on the development split for the record). | Final ablation data |
| T-5.6 | Write `eval/reports/ablation.md`: accuracy by configuration and category, runs versus correct, repairs used, failure-tag counts, cost, and latency. | Report |
| T-5.7 | Review SC-04, SC-05, and SC-10 against the results; revise targets only with a written rationale (Q-06). | Targets confirmed or amended |

**Checkpoint:** if configuration D scores below 50% on the test split, pause before M6 and choose among improving the views and glossary, adding static few-shot examples (configuration E), or using `deepseek-v4-pro` for SQL generation (after calculating the cost impact).
**Tests:** re-running from cache reproduces the numbers exactly; the spend ledger matches the provider balance.
**Acceptance criteria:** ablation table for A to D on development and test splits; failure taxonomy; measured cost and latency; Q-06 resolved.
**Deliverables:** LLM client, prompts, evaluation reports.

### M6. Ask mode complete

**Objective:** the full Ask experience with routing, scope, grounding, and honest failure handling.

| Task | Description | Expected outcome |
|---|---|---|
| T-6.1 | Router (JSON with Pydantic validation; invalid output becomes `clarify`); clarify and refuse behaviours (PRD section 8.2). | Router tested |
| T-6.2 | Answer writer, deterministic output-component selection (PRD section 8.1), and scope assembly (period, definitions, sample size, assumptions, partial-period warnings from `data_coverage`). | Responses carry scope |
| T-6.3 | Grounding check (technical design, section 8.5) and causal-language lint with unit tests; measure and tune the false-positive rate on development answers. | Checks tuned |
| T-6.4 | Check the current LangGraph API (Q-05), then wire the graph: router, SQL generation, validation, execution, repair loop, answer, checks; trace recorder. | Graph working |
| T-6.5 | Anchor-date handling ("last month" resolves against 2018-08-31) and the minimum-volume ranking rule. | Rules enforced |
| T-6.6 | Decide whether to merge router and SQL generation, using measured cost and accuracy. | Decision recorded |
| T-6.7 | Evaluate routing (SC-07) and faithfulness (SC-06) on all labelled items. | Metrics reported |

**Tests:** fake-LLM graph tests for every edge (success, validator rejection, execution error, repairs exhausted, budget block, clarify, refuse) · grounding unit tests with true and false numbers.
**Acceptance criteria:** SC-06 and SC-07 measured and reported; PRD Examples 1 and 2 produced end to end (cache permitted); Q-05 resolved.
**Deliverables:** router, answer writer, grounding and lint modules, graph, evaluation results.

### M7. Investigate mode

**Objective:** two playbooks that compute findings in code and narrate them with calibrated language.

| Task | Description | Expected outcome |
|---|---|---|
| T-7.1 | Playbook interface: typed parameters, fixed SQL steps with bind parameters, findings object, verdict. | Interface defined |
| T-7.2 | `late_delivery_diagnosis`: KPI versus baseline; stage decomposition (handling, transit, promised); geography; category; seller concentration (minimum 30 orders); review impact. Verdict is *elevated* if the late rate is at least baseline plus 3 percentage points, at least 1.5 times baseline, and the sample is at least 100 orders. Thresholds are tuned on development scopes only. | Playbook working |
| T-7.3 | `low_review_diagnosis`: score and 1-star share versus baseline; split of 1-star reviews by late, on-time, and undelivered orders; category and seller contributors (minimum 30). | Playbook working |
| T-7.4 | Narration prompt and checks: number grounding, `top_driver` agreement, and causal lint. | Checks wired |
| T-7.5 | Scope inheritance and at least five follow-up evaluation cases. | Follow-ups working |
| T-7.6 | Investigation evaluation: 15 cases plus 2 planted anomalies on the mini fixture. | Report |
| T-7.7 | Reproduce PRD Example 3 from the playbook output: late 19.0% (1,328 of 7,003), baseline 5.8%, transit 13.0 versus 9.1 days, RJ 34.5%, BA 31.5%, MG 20.4%, 465 sellers with a top-five share of 11.5%, reviews 2.07 versus 4.21. Any difference is investigated and either the playbook or the PRD is corrected. | Example reproduced |

**Tests:** every playbook step passes the validator (M4 scaffold) · negative controls produce the "nothing notable" verdict · planted anomalies are identified.
**Acceptance criteria:** SC-08; FR-11 and FR-12 satisfied.
**Deliverables:** playbooks, narration module, `eval/reports/investigation_report.md`.

### M8. Safety suite

**Objective:** the safety claims are backed by a published list of attempts and results.

| Task | Description | Expected outcome |
|---|---|---|
| T-8.1 | Finalise `attacks.yaml` (at least 40 cases; technical design, section 8.7). | Case file final |
| T-8.2 | Deterministic runner (no LLM), ready for CI. | Runner |
| T-8.3 | Injection suite: `injtest` schema, the test-only `get_review_text` tool, poisoned synthetic rows with canaries (technical design, section 7.5). | Suite |
| T-8.4 | Resource tests: Cartesian joins, large `IN` lists, deeply nested subqueries, runaway repair loops. | Tests |
| T-8.5 | `eval/reports/safety_report.md`: successes and failures per category; every failure analysed and fixed or documented. | Report |

**Tests:** the SC-01 statements re-run · all deterministic cases pass.
**Acceptance criteria:** SC-02 (zero of at least 40 attacks succeed). If an attack succeeds, the underlying cause is fixed (not the test) and the suite re-run.
**Deliverables:** attack suite, injection fixtures, safety report.

### M9. API, tracing, and UI

**Objective:** a usable, inspectable product.

| Task | Description | Expected outcome |
|---|---|---|
| T-9.1 | FastAPI endpoints and Pydantic contracts (technical design, section 9); access code; rate limit; `/v1/budget`. | API |
| T-9.2 | Trace recorder wired end to end; administrative queries for p50 and p95 latency, cost per question, and rejection rate. | Traces and queries |
| T-9.3 | Streamlit UI: input, four result components, scope panel, evidence panel, follow-up suggestions, scope bar, cost and latency line. | UI |
| T-9.4 | Confirm Streamlit is sufficient (Q-08); reproduce PRD Examples 1 to 3 end to end. | Examples reproduced |
| T-9.5 | Error states: budget exhausted, validation failure, timeout, clarify, refuse, untraced number. | Error handling |

**Tests:** API contract tests · no secrets in logs or traces (search for the key) · the three examples render correctly.
**Acceptance criteria:** FR-01, FR-08 to FR-10, FR-15, and FR-16 satisfied; NFR-06 met; Q-08 resolved.
**Deliverables:** API, UI, trace queries.

### M10. Hardening, comparison, and documentation

**Objective:** a credible, reproducible, well-documented repository.

| Task | Description | Expected outcome |
|---|---|---|
| T-10.1 | CI: lint, unit tests, integration tests (Postgres service container with the mini fixture), deterministic safety tests, secret scan; no LLM calls. | CI green |
| T-10.2 | Variance: run configuration D three times on the test split and report the spread. | Variance reported |
| T-10.3 | Model comparison: `deepseek-v4-pro` on the test split and five investigations; accuracy, cost, and latency table. Include configuration E if M5 indicated it. | `model_comparison.md` |
| T-10.4 | Cost and latency report from the trace tables. | Report |
| T-10.5 | README: overview, architecture diagram (technical design, section 2), results tables, precisely worded safety claims, limitations (technical design section 7.4, PRD non-goals), cost, and run instructions. | README |
| T-10.6 | Fresh-clone test in a new directory following only the README (SC-11). | Passes |
| T-10.7 | Optional: evaluate a second, free-tier model (Gemini `gemini-3.5-flash-lite`, calibrated in M0b: 15 RPM, 500 RPD) on the test split (Q-10). | Decision recorded |

**Acceptance criteria:** SC-09, SC-10, and SC-11 met; README complete; CI green; Q-10 resolved.
**Deliverables:** CI workflow, evaluation reports, README.

### M11. Deployment and packaging

**Objective:** a temporary public demo and permanent supporting artifacts.

| Task | Description | Expected outcome |
|---|---|---|
| T-11.1 | Confirm AWS free-plan terms, eligible instance types, and storage and IPv4 charges (Q-07). Create the account and set a budget alert before launching anything. | Terms documented |
| T-11.2 | Launch the instance, install Docker, deploy with Compose, copy the CSVs, load the data, and run `smoke.py`. | Deployment live |
| T-11.3 | Public-demo protections (FR-20; technical design, section 10.4); test the kill switch; settle the HTTPS approach (Q-09). | Protections verified |
| T-11.4 | Demo video of at most three minutes: the three example interactions, a blocked attack, and the ablation table. | Video |
| T-11.5 | Teardown checklist and key rotation for the end of the demo window. | Checklist |

**Acceptance criteria:** SC-12 met; a public link answers a question; teardown plan written; Q-07 and Q-09 resolved.
**Deliverables:** deployment, demo video, teardown checklist.

## 4. Descoping priorities

If scope must be reduced, items are cut in this order:

1. F-16 (second provider) and F-15 (seller-scoped mode).
2. Configuration E and optional comparison extras.
3. The live AWS deployment. The video and README remain as the durable artifacts.
4. F-11 (model comparison).
5. One Investigate playbook. The late-delivery playbook is retained because it has the strongest measured signal.

The validator, database roles, golden-set evaluation, safety suite, budget guard, and honest reporting are not descoped.

## 5. Where open questions are resolved

| Question | Milestone |
|---|---|
| Q-01 Olist licence | M1 |
| Q-02 DeepSeek API details | M0 |
| Q-03 PostgreSQL behaviours | M2, M4 |
| Q-04 SQL parser choice | M4 |
| Q-05 LangGraph API | M6 |
| Q-06 Baseline versus targets | M5 |
| Q-07 AWS terms | M11 |
| Q-08 Streamlit sufficiency | M9 |
| Q-09 HTTPS for the demo | M11 |
| Q-10 Second model | M10 |

## Document history

| Version | Date | Change |
|---|---|---|
| 1.0 | 2026-10-15 | Initial version. |
| 1.1 | 2026-10-15 | Commits and paid calls require the project owner's approval. M0 split into M0a (local setup, free) and M0b (provider calibration, paid, approval required). |
| 1.2 | 2026-10-15 | M2 acceptance includes the empty month 2016-11; mini fixture moved to M7/M10. |
| 1.3 | 2026-10-15 | Tasks rewritten for the Gemini free tier (DeepSeek top-up failed). |
| 1.4 | 2026-10-16 | DeepSeek restored as the primary provider (version 1.2 text restored); Gemini free tier named as the second model for T-10.7. |
