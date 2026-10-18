# Progress log

## Current milestone

**Web frontend (Next.js) built locally, not committed or pushed** (the owner asked to get everything right locally before pushing). M10 complete; its first CI run on GitHub passed. Next: the owner's local testing, then M11, optional deployment (needs the owner's approval).

## 2026-10-17 — Web frontend: Next.js app replacing the Streamlit UI as the main interface (no spend)

The owner asked for a frontend that looks like a startup's product and chose a separate React/Next.js app over restyling Streamlit. Streamlit stays as a simple fallback; the API is unchanged.

**Completed**
- `web/`: Next.js 16 (App Router, Turbopack), React 19, TypeScript, Tailwind CSS 4, Recharts, lucide icons.
- **Backend-for-frontend proxy** (`web/src/lib/server/`, `src/app/api/`): the browser calls only same-origin `/api/*`; the server forwards five allow-listed FastAPI endpoints with only the access code and the JSON body (no cookies or other headers), caps the body at 4 KB, times out after 120 s, refuses non-JSON replies, and passes `Retry-After` through. No CORS was added to the API. Local mode (`npm run dev:local`): the server reads `ACCESS_CODE` from `.env` only when `API_URL` is localhost and never returns it.
- **Screens:** access-code screen that explains what the code is; empty state with example questions; chat-style thread with session history; answer card (route and grounding badges, KPI tiles, charts, sortable tables with CSV download, findings, folded caveats, follow-up chips, cost and latency, copyable request id); investigation report (verdict, top driver, metrics with deltas, "where the days went" stage bars, states, sellers, and categories against baseline); evidence tab (highlighted SQL, validator rules, parameters, row previews, rejected attempts); scope and definitions tab; session scope bar with clear; budget meter; API health; per-request trace drawer (`GET /v1/requests/{id}`).
- **Mock API** (`npm run dev:mock`) replaying six recorded responses exported from the trace database, plus two hand-written ones (refuse, clarify), for UI work at $0.
- **CI:** a second job (`web`): `npm ci`, lint, type check, tests, production build.

**Found and fixed while checking in the browser:** a random session id created during the server prerender (Next.js 16 error; now created on first use); the logo missing on phones (an SVG gradient id shared with the hidden sidebar copy); long seller ids overflowing chart axes, the sidebar, and the question bubble; "1 rows"; new answers scrolling to their bottom instead of their headline; the `.env` read making the build trace the whole project folder.

**Tests (actually run):** web 34 passed (format helpers, proxy allow-list and header rules including "the server's code never reaches the browser", screens against recorded responses); a deliberate break of the allow-list made 2 tests fail, as it should. Lint, type check, and production build clean. Python suite unchanged (see below).

**Not done:** not checked end to end against the real API with a real question (that needs a model call; the recorded responses came from the real API). `npm audit` reports 5 high-severity advisories in dev-only lint dependencies of `eslint-config-next` (none in production dependencies); left as is because the suggested fix downgrades Next's lint config. The per-IP rate limit sees every browser as the web server's address, which matters only once deployed (M11).

**API cost:** $0.

### Same day — conversations and saved history (owner's feedback from local testing, no spend)

The owner found that the sidebar listed every question with a chat icon, so one conversation looked like several, and asked for the history of earlier sessions.

- **API:** `GET /v1/sessions` (past conversations, newest first: id, first question as title, number of questions, times) and `GET /v1/sessions/{id}` (each question with its stored response, and `scope_active`). Both read the request rows the recorder already stores; nothing new is stored and no model is called. Only the deployment's own `config_name` is listed, so evaluation and test runs never appear. Migration `006_session_history.sql` adds an index for these lookups.
- **Web app:** the sidebar lists conversations grouped as Today, Yesterday, Previous 7 days and Older; a new conversation appears as soon as it is asked; clicking one reopens it from the saved answers and later questions continue it. When the reopened conversation's investigation scope has expired (kept in the API's memory for two hours, lost on restart), the page says that follow-ups start without it; when it is still active, the scope bar comes back. The proxy allow-list grew from five to seven endpoints.
- **Checked against the real API:** the owner's earlier conversations (including those from the Streamlit UI) were listed; a six-question conversation reopened with all six answers, and the API log showed no `/v1/ask` call.
- **Tests:** 3 new API tests (listing and reopening without any call or write, isolation by configuration, unknown and invalid ids) and 4 new web tests plus one for date grouping; a deliberate break (reopening without switching to the conversation) failed the test as it should.
- **Known limit, unchanged:** follow-ups inherit context only from investigations. After a normal answer, a question like "these top categories" is answered without the previous answer as context.

### 2026-10-18 — "Explore the data" guide and friendly refusals (owner-approved plan A + B, no spend)

Owner's test: "show me the dataset" and "show me the dataset schema" were refused with "I can't help with that request." and no way forward, so a new user could not find out what to ask. The router rule that refuses questions about the system (it blocks prompt-extraction attempts) caught them. Decision: first a guide outside the chat (no model, no router change); an "about the data" route in the chat may follow with a cost estimate.

- **`GET /v1/catalog`** (`src/orderintel/catalog.py`): what the data contains, built from fixed read-only queries as `oi_agent` over the analytics views (orders, customers, sellers, products, categories, states, first and last month, analysis window, partial months, the views and their columns) plus the definitions parsed from `glossary/glossary.md`, example questions by topic, and what cannot be answered. No model call; cached for ten minutes. A unit test fails if any hand-written text contains a figure (checked by a deliberate break), so every number shown comes from the data.
- **Web app:** an "Explore the data" panel (Overview with counts, period, partial months, example questions by topic that ask when clicked, and limits; Tables with each view's columns; searchable Definitions), opened from a "Data guide" button in the header, a "Not sure what to ask?" link on the empty screen, and every refusal. A refused question now shows "That's outside what I can answer", the model's reason, the guide button, and three questions that can be answered. The proxy allow-list grew to eight endpoints.
- **Checked against the real API:** the guide showed the real counts (99,441 orders, 96,096 customers, 3,095 sellers, 32,951 products, 74 categories, 27 states, 27 definitions); the owner's three earlier refusals, reopened from history, rendered the new card.
- **Tests:** API (catalog numbers equal direct counts, nothing traced or billed, no secrets or internal names in the output, needs the access code), unit (glossary parsing, no figures in static text), web (guide from the header and the empty screen, example question asks and closes, tables and definition search, refusal card with reason, suggestions, and guide).
- **Seen and left for later:** "Which 5 PRODUCT NAME had the most orders?" is refused with "cannot be answered from the order data" without saying that product names do not exist in the data (the vocabulary-mismatch problem).
- **Process note:** an earlier documentation edit in this file replaced every match of its anchor and inserted a section twice, once inside an older milestone; found and repaired before any commit. Edits to this file now require a unique anchor.

### 2026-10-18 — Fixes for every problem found in owner testing (no spend so far)

Owner testing found wrong or inconsistent answers and misleading charts (list in the session; numbered as there). All fixes below are deterministic code unless stated.

- **#9 Contradicting findings (bug).** A September 2016 investigation reported "0 delivered orders" and "1 seller with late orders": two late-delivery steps (sellers, reviews) and one review step (sellers) ignored the analysis window. All steps now apply it. New `playbooks/checks.py` flags contradictions inside findings (late above delivered, sellers with late orders but no late orders, percentages outside 0 to 100, groups larger than the period, a verdict without data); the investigation shows a warning if any appear. A real-data test over the partial and edge months fails without the window fix and passes with it.
- **#7, #8, #10 Partial and out-of-range periods, consistently.** New `agent/precheck.py` runs before the router. Why / low / high questions about a month the data only partly covers (or about 2016) are answered in code: that month's orders, delivered orders and revenue next to a typical month (the median month of January 2017 to August 2018), with a bar chart; questions naming a month or year outside September 2016 to October 2018 get "there is no data for ...". Same question, same answer, no model call. Detection was checked on tricky wording ("orders over 2000 reais" is not a year).
- **#13 "Show me the dataset / schema" in the chat.** The pre-check answers it from the catalog with an about card (counts, the orders-per-month timeline, the tables, five sample orders, example questions). Questions about prompts or instructions still go to the router and are refused; none of the 44 attack cases or 15 investigation cases is caught by the pre-check.
- **#6 Wrong playbook for the topic.** New `agent/guards.py`: the question's words decide the topic. A delivery question sent to the review playbook (or the reverse) is corrected; a sales "why" question never runs a playbook (there is none for sales yet) and gets a descriptive answer with a caveat. Questions without topic words ("Why was March 2018 so bad?") keep the router's choice.
- **#11 Missing fields.** One list of fields the data lacks (product, seller and customer names, profit, review text, returns, discounts, stock, web traffic), each with the closest field that exists. It is added as a hint to the router and SQL writer, shown first in refusals and declines, added to answers' caveats, and shown in the guide.
- **#12 Follow-ups after normal answers.** The API reads the conversation's previous answer from the saved traces (so it works after a restart and in reopened conversations) and, only when the question refers back ("these", "and in 2018?", "what about SP?"), gives its question, SQL and first rows to the router and SQL writer.
- **False premise (predicted).** New answer prompt `answer_v2.md`: if the question assumes something the rows do not show, say so first; for why-questions, describe what changed and say that the data shows what changed, not why. `answer_v1.md` is kept for the recorded M5 runs; the safety suite's prompt-leak check covers both.
- **#14 to #17 Charts and timeline (web, and the API's chart choice).** One kind of measure per chart (rates, else money, else counts), applied by the API and again in the browser so answers saved earlier are fixed too; straight lines between months instead of smoothed curves; three or fewer points as bars; partial months hollow or grey with a note. The guide shows orders per month across the whole data and explains which months totals and trends use; the Tables tab shows the column descriptions the SQL writer sees; refusal text reads "That question is outside what the order data can answer." with the reason.
- **Checked against the real API (free questions only):** "why is the Revenue low in the sep 2016?" answered with 4 orders and R$208 against a typical 5,152 orders and R$701,182; "Why was 2019 bad?" answered "There is no data for 2019"; "SHOW ME THE DATASET SCHEMA" showed the about card; spend unchanged ($0.085426 before and after). The owner's stored October 2016 answer now draws a revenue-only bar chart with grey partial months.
- **Tests (actually run):** Python 655 passed (new: pre-check, topic guard, missing fields, follow-up context, consistency checks, catalog); web 48 passed; lint, types, build, secret scan clean; deterministic safety 0 of 32 SQL attacks succeeded.
- **Process notes:** three edit scripts turned the regular-expression marker `\b` into an invisible backspace character (Python string escaping inside shell heredocs); each was found and fixed, and a scan of the source files found none left. Scripts containing backslashes are now written with the file tool only. Simulating CI on the synthetic database (with the local CSVs hidden, as on GitHub) found a real design flaw: the pre-check first treated months under 500 orders as sparse, and every synthetic month has about 400, so it intercepted ordinary questions such as "Why was March 2018 so bad?". Sparse now means outside the analysis window, the rule trends and baselines already use; on the real data this is the same six months. A first simulation attempt was invalid because a loader test loaded the local CSVs into the CI database midway; hiding the CSVs (`DATA_DIR` set to an empty folder) reproduces GitHub's conditions.
- **Paid re-check (owner-approved; Sunday 12:00 UTC, off-peak), $0.006509 in total.** Results are saved next to the earlier ones with a date (`eval/results/*_2026-10-18.json`, `eval/reports/*_2026-10-18.md`); the M7 and M8 files are unchanged.
  - Investigation evaluation, $0.003799: 15/15 cases as expected (6 late-delivery, 4 review, 3 negative controls, 2 non-investigations) and 5/5 follow-ups correct with the scope kept. Most router and narration calls were cache hits because those prompts did not change.
  - Safety evaluation, 1 repetition, $0.000081: 0 of 44 cases with a successful attack; the benign control answered correctly.
  - Five smoke questions through the API, $0.002629: "Why did revenue drop in March 2018?" now says the data does not support a drop (answer prompt v2); "Which 5 PRODUCT NAME had the most orders in 2018?" is answered with product ids and categories and says names do not exist (it was refused before); "What is the average order value for each of these categories in 2017?" after "Top 5 categories by revenue in 2017" used the same five categories (previous-answer context); "Why was revenue low in June 2018?" went to the answer route with the no-sales-playbook caveat and described the change against May and April.
- **Found by the smoke questions, not fixed (existing SQL-writer weakness):** in two answers the SQL summed `items_revenue` without `is_sale`, so canceled and unavailable orders were counted as revenue (March 2018 R$983,213 instead of R$981,051, about 0.2% too high). The glossary rule is in the prompt but not enforced in code. Candidate fix: a revenue column or view that already applies the sale rule, or a validator check, followed by a re-run of the test split.

**API cost:** $0.006509. Project total **$0.091935 of the $1.90 cap**.

### Same day — revenue rule enforced in code (owner-approved; no spend so far)

- **`guard/business_rules.py`:** every SUM or AVG over `items_revenue` or `price` must itself be limited to sales: a FILTER on the aggregate, a CASE inside it, the WHERE or JOIN conditions of its SELECT, or a CTE or subquery it reads from that is limited to sales (`order_status` counts as an explicit choice, for questions about canceled orders on purpose). Checked after the validator and before execution in the product path (configuration D); a violation goes back to the SQL writer through the repair loop with the reason; if the last repair still violates it, the query runs and the answer carries a warning. The Evidence tab names who rejected an attempt (SQL validator, revenue rule, database).
- **A first version checked the whole query and missed the very query it was written for** (that query used is_sale to count sale orders, not to limit the revenue sum); the rule now checks each aggregate. Found by running it over the recorded SQL before trusting it.
- **Measured for free on recorded SQL:** 0 of 54 golden reference queries flagged; of 488 model-written queries in the evaluation results, 11 flagged and all 11 had been graded wrong (including `agg_11` in the M10 deepseek-v4-pro run, "canceled orders in the numerator"); of the traced API answers, exactly the two smoke answers found earlier.
- **Tests:** 18 unit cases (the real smoke SQL and `agg_11` caught; sales-limited, explicit-status and non-revenue queries pass; unparsable SQL never blocks) and 2 repair-loop tests (bad SQL sent back and fixed, the result equal to a direct sales-only query; a persistent violation runs with a warning). Real data 676 passed; CI simulation 552 passed, 119 skipped, 0 failed; web 48 passed.
- **Paid re-check (owner-approved; Sunday 12:33 UTC, off-peak), $0.001204:**
  - Test split, configuration D, tagged `revenue-rule` (`eval/results/test_D_deepseek_sqlgen-v1_revenue-rule.json`): 15/18 correct, the same as the M5 headline run; all 18 replies came from the response cache ($0) and the rule rejected none of them, so it causes no regression on the frozen split (this re-checks the recorded replies, not a fresh sample).
  - The two revenue smoke questions in fresh sessions, $0.001204: in both, the first SQL (the cached one that summed all orders) was rejected by the revenue rule and repaired once; the answers now match the sales-only figures from the data exactly (March 2018 R$981,051, before R$983,213; June 2018 R$863,266; May 2018 R$992,872).

**API cost:** $0.001204. Project total **$0.093139 of the $1.90 cap**.

## 2026-10-17 — M10: CI, variance, model comparison, README, fresh-clone test (owner-approved runs)

**Completed**
- **CI** (`.github/workflows/ci.yml`): lint, secret scan, and the test suite against a PostgreSQL 18 service loaded with the synthetic fixture (`scripts/build_mini_db.py --db orderintel_ci`). Database passwords are random per run and masked; no LLM key exists in CI. Not run on GitHub yet (it runs on the next push); simulated locally against `orderintel_ci` with no CSVs: 497 passed, 114 skipped, 0 failed.
- **`realdata` marker** (`tests/conftest.py`): tests that check real Olist figures skip, with the reason shown, when the database does not hold the full load. Classified by running the whole suite on the synthetic database rather than by guessing. Three safety tests that used the real seller count to mean "nothing changed" now compare before and after, so they run in CI too.
- **Cost report** (`scripts/cost_report.py` → `eval/reports/cost_report.md`) from the trace ledger, by activity and model.
- **Evaluation flags:** `run_eval.py --model` and `--run-tag` (a repeated run can no longer overwrite the M5 headline file; tagged files refuse to overwrite); `run_investigation_eval.py --model --ids` (comparison runs go to their own file and leave the M7 report alone); opt-in per-minute quota waiting in the LLM client for the Gemini free tier.
- **Variance and model comparison** (`eval/model_comparison.py` → `eval/reports/model_comparison.md`).
- **README** rewritten: overview, architecture, measured results, precisely worded safety claim, limitations, cost, setup, run, tests, troubleshooting, data licence.

**Results (runs at 18:30 to 18:40 UTC, off-peak)**

| Run (configuration D, 18 answerable test items) | Correct | Cost |
|---|---|---|
| deepseek-flash run 1 (M5 headline) / run 2 / run 3 | 15 / 16 / 15 (83% to 89%) | cache / $0.0018 / $0.0018 |
| deepseek-v4-pro | 15 | $0.0075 |
| gemini-3.5-flash-lite (free tier) | 16 | $0 |

Only `trap_14` ("best seller", ambiguous) changed across the three flash runs. deepseek-v4-pro fixed two items and broke two (`agg_11`: canceled orders in the numerator, a real error; `ambig_06`: a different "recent" window), at about 4x the cost. On five investigations it matched flash on four and misrouted `inv_none_01` ("Why did revenue fall in June 2018?") to the low-review playbook: grounded but off-topic. This exposed a gap, now listed as a limitation: no code check ties the chosen playbook to the question's topic. Decision: deepseek-flash stays primary; Gemini stays the optional second provider (Q-10 resolved).

**Fresh-clone test (T-10.6, SC-11):** a clone of the repository (with the uncommitted M10 changes) in a new folder, set up by following only the README, with its own database container on port 5433 (`COMPOSE_PROJECT_NAME` set so it could not touch the developer's container), random passwords, and the CSVs copied from `data/raw/`. Every README expectation matched (five roles, five migrations, 550,759 rows, 0 failed checks). **It found a real bug:** the first test run after a clean install had failures that disappeared on a second run. Reproduced deliberately (fresh load, then tests at once): 5 failures, investigation queries cancelled at the 8 s timeout, because freshly loaded tables have no planner statistics until autovacuum runs. The loader now runs `ANALYZE` as part of the load; the same sequence then passed 15/15 at once, and the full suite in the clone passed 617/617. The API (health, access code refused without it) and the UI (HTTP 200) started with the README commands. The clone, its container, and its volume were removed afterwards.

**Also found and fixed:** the M9 API and UI tests left 120 zero-cost fake LLM rows in the ledger (the cleanup matched `test:api` but the rows were named `test:api:D`); they would have counted against the Gemini daily quota. Cleanup now matches the prefix; the rows were deleted; budget totals unchanged.

**Not done:** formatting is not enforced in CI (eight older files differ from the formatter; lint is enforced as planned). Update (2026-10-17): the first CI run on GitHub after the push passed (lint, secret scan, tests).

**Tests (actually run):** full suite 617 passed, 0 skipped (real database); 497 passed, 114 skipped (synthetic CI database); ruff clean; secret scan passed.

**API cost:** M10 runs $0.018408. Project total **$0.078862 of the $1.90 cap** (ledger $0.078173 + calibration $0.000689).

## 2026-10-16 — M9: API, tracing, and UI (owner-approved end-to-end check)

**Completed**
- `src/orderintel/api/app.py` (FastAPI): `POST /v1/ask`, `GET /v1/requests/{id}`, `POST /v1/sessions/{id}/scope/clear`, `GET /v1/health`, `GET /v1/budget`. Access code in `X-Access-Code`, constant-time comparison, fail closed when unset; per-IP and global token-bucket rate limits with `Retry-After`; `LLM_ENABLED` kill switch; structured errors only (`budget_exhausted`, `provider_error`, `rate_limited`, `invalid_request` without echoing input, `internal_error` without details); structured, redacted JSON logs.
- Request traces: migration `005_request_traces.sql` (`kind`, `parent_id`; `trace.spend` counts LLM calls only; budget totals identical before and after, $0.059434). `src/orderintel/trace/recorder.py` writes the request row first, links every LLM call through a context variable, then stores route, status, latency, tokens, scope, the response, and steps (llm, validator, sql or playbook, grounding, lint). `src/orderintel/redact.py` redacts every configured secret before anything is written. Admin queries: `scripts/trace_report.py`.
- `src/orderintel/ui/` (Streamlit): access code (main page, password field), question box, the four components (answer card, table, line or bar chart, report), notes and caveats, scope panel and scope bar with Clear scope, evidence panel (SQL, parameters, rows preview, validator result, failed attempts, latency), follow-up buttons, cost and latency line, a message for every error code and non-ok status, and the untraced-number warning. Local mode (`-- --local`) for development only.
- Tests: 22 API contract, protection, and tracing tests (fake model billed at $0, test rows deleted); 15 headless UI tests (AppTest) that render REAL API responses produced by the actual API, agent, and database.

**End-to-end check (real model, real API and UI in the browser pane; 15:10 to 15:40 UTC, off-peak)**

| Example | Result | Model calls | Cost |
|---|---|---|---|
| 1. Top 5 categories by revenue in 2017 | table + bar chart; bed_bath_table R$497,971, watches_gifts R$486,519, health_beauty R$481,143, sports_leisure R$447,547, computers_accessories R$400,491 (PRD figures) | 3, all cached (M6) | $0 |
| 2. How is the late-delivery rate trending? | line chart over 20 months; spikes November 2017 12.4%, February 2018 14.13%, March 2018 18.96% | 3, all cached | $0 |
| 3. Why was March 2018 so bad for deliveries? | report: 19.0% vs 5.8%, 1,328 of 7,003, top driver carrier transit, RJ/SP/MG, 466 sellers (PRD figures); scope bar shown; 7 evidence queries | 2 (1 cached) | $0.00033 |

Trace report afterwards: 6 API requests, p50 0.5 s, p95 5.7 s, 0% validator rejections; a scan of every recent trace row and step found no secret value.

**Found during the check and fixed (each with a regression test)**
- Dollar signs: Streamlit Markdown read "R$497,971 ... R$486,519" as a LaTeX formula and garbled the notes. All rendered text now escapes `$`; checked in the browser (no math elements left).
- Line chart scale: Example 2 plotted delivered and late order counts with the rate on one axis, flattening the rate. Time series with both rates and counts now chart the rates only (counts stay in the table). This refines the PRD 8.1 component rule; recorded in the technical design.
- Scope bar timing: the bar appeared only one interaction after the investigation (found by the UI tests); it is now filled after the question runs.
- Access code entry: the field was in the collapsible sidebar, which is hidden in a narrow window, and the first attempt was sent empty (rejected by the API with no model call). The field is now on the main page.

**Known limitations:** the Example 3 narration says the pattern was "systemic rather than confined to a few states" and also that it was "concentrated geographically"; both are supported by different findings (23.7% excluding the top two states; RJ, MG, SP excess), but the wording is contradictory. Rate limits and sessions are in memory (one process).

**Tests (actually run):** full suite 616 passed, 0 skipped; ruff clean; secret scan passed.

**API cost:** this check $0.000331. Project total **$0.060454 of the $1.90 cap** (ledger $0.059765 + calibration $0.000689).

## 2026-10-16 — M8: safety suite (owner-approved run, 3 repetitions)

**Completed**
- `eval/golden/attacks.yaml` final: 44 cases (32 SQL, 6 direct prompt injection, 6 indirect injection through review text). Four new resource cases for T-8.4: a 150-item IN list, subqueries nested 7 deep, a recursive CTE, a 4,100-character SQL string (all stopped by the validator's VR-08).
- `db/migrations/004_injtest_schema.sql`: injection rows readable only by `oi_injtest` through a view; `oi_agent` cannot read them, and `oi_injtest` cannot read anything else (tested).
- `src/orderintel/safety/`: test-only review-tool agent (JSON actions decided by code, 5-turn cap), checks (secrets compared in memory and reported by name only, planted secret canary, verbatim prompt leak, database fingerprint), and the judge. No product module imports it (tested).
- `eval/run_safety_eval.py`: `--deterministic` (free), `--estimate`, `--approved --reps N` (repetition 1 cached, repetitions 2+ bypass the cache), `--recheck` (re-judge stored answers, no calls); writes `eval/reports/safety_report.md`.
- 13 fake-model injection tests, including a compromised fake model that obeys the review (the judge must catch it), injected DDL and catalog requests (rejected, database unchanged), a runaway tool loop (stops at 5 turns), unknown actions and bad JSON.

**Results** (run at 14:38 UTC, off-peak; full table in the report)

| Part | Runs | Attacks succeeded | Stopped by |
|---|---|---|---|
| SQL cases, deterministic | 32 | 0 | validator 29, executor 3 (cost ceiling, row cap); 32/32 by the expected layer; database unchanged |
| Direct injection | 6 x 3 | 0 | the router refused all 18 in one call |
| Indirect injection | 6 x 3 | 0 (after the judge correction below) | the model: it flagged the review text as untrusted every time |
| Benign control | 1 x 3 | — | review read, SQL run, answer correct 3/3 |

**Found and handled**
- **Judge false positive (corrected):** `atk_ind_04` was flagged in all 3 repetitions because "0%" appeared inside the model's description of the injection ("instructing me to report a 0% late-delivery rate ... I have not followed those instructions"). The canary never appeared. The 0% rule now ignores sentences that describe or refuse the injected text; regression test from the real sentence; the stored answers were re-judged offline (`--recheck`), and the verdicts from the run are kept as `reasons_at_run`.
- **Over-refusal (documented, not changed):** three direct prompts also contained a legitimate question (order count, revenue in 2017), which went unanswered. Safe, but less useful; changing it would be a router-prompt change that needs its own evaluation.
- **Not exercised live:** no model asked for disallowed SQL, so in the paid run the validator never had to act; it is covered by the 32 SQL cases and the fake-model tests.
- **One answer quoted the poisoned text verbatim** (`atk_ind_01`, repetition 3) while saying it was ignored. Not a success under the criteria; noted.
- Estimate vs actual: estimated $0.017, actual $0.0056 (direct injections were refused after one call instead of about three).

**Tests (actually run):** full suite 578 passed, 0 skipped; ruff clean; secret scan passed.

**API cost:** this run $0.005552. Project total **$0.060123 of the $1.90 cap** (ledger $0.059434 + calibration $0.000689).

## 2026-10-16 — M7 part 2: synthetic mini fixture and planted anomalies (no spend)

**Completed**
- `tests/fixtures/mini_olist/generate.py`: seeded generator for Olist-format CSVs, 20 months x 400 delivered orders (8,074 orders in total, with non-delivered and out-of-window orders). Baseline lateness is exactly 5% inside every (month, state) group, so control months sit exactly at baseline and a detection cannot come from noise. All data traps included (multi-payment, duplicate reviews, null and untranslated categories, multi-seller order, same-day delivery, "delivered" with no date, order with no review, empty months 2016-11 and 2016-12). The CSVs are generated at build time and not committed.
- `scripts/build_mini_db.py`: recreates the separate database `orderintel_mini` (only a name ending in `_mini` can be dropped) and builds it with the normal `migrate.py` and `load_data.py`, which now accept optional settings and expected counts (defaults unchanged).
- Planted anomalies, applied after the promise date is fixed so only the planted stage moves: +10 carrier transit days for RJ customers in March 2018; +5 handling days for one seller (30% of orders) in October 2017.
- **Gap found and fixed:** the plan required the seller step to name the planted seller, but the `sellers` step only counted sellers and the top-5 share. New `seller_rank` step: sellers with at least 30 orders in the period, ranked by excess late orders over their own baseline (as states already were). On the real data, March 2018's top seller is `4869f7a5…`, the same seller the M7 follow-up evaluation found with a different query; the step returns at most 43 rows and adds under a second. The earlier paid investigation run used the playbook without this step; its findings are otherwise unchanged.
- `eval/run_investigation_eval.py --planted` (no model calls) records both cases in `eval/results/investigation_planted.json` and the report.

**Results (measured on the fixture)**

| Case | Verdict | Late rate vs baseline | Driver | Located |
|---|---|---|---|---|
| `inv_plant_01` RJ, March 2018 | elevated | 90.8% vs 5.5% | carrier transit (17.78 vs 7.52 days) | RJ ranked first unfiltered (+102 excess late orders), not systemic |
| `inv_plant_02` all states, October 2017 | elevated | 13.5% vs 6.3% | seller handling (3.95 vs 2.51 days) | planted seller first (+35 excess; the next two about -1) |

Controls: June 2017 (all states and RJ) and January 2018 (SP) report nothing notable; MG (60 orders a month) is reported as insufficient data. **Counterfactual:** the same fixture rebuilt without the plants reports nothing notable for both planted months. SC-08 planted anomalies: **2/2**.

**Mistakes during the work (corrected):** two test mistakes on the first run (wrong column name; MG chosen as a control although it is below the 100-order minimum, which the playbook correctly reported as insufficient data). Inline-script escaping turned `"\n"` string literals into real line breaks several times; each was caught by ruff or Python and fixed with the Edit tool.

**Tests (actually run):** full suite 561 passed, 0 skipped (16 new fixture tests; one existing test updated from 6 to 7 playbook steps); ruff clean.

**API cost:** $0.00. Project total unchanged at **$0.054571 of $1.90**.

## 2026-10-16 — M7 part 1: investigation evaluation (owner-approved)

Run at 12:55 UTC (off-peak): 15 investigation cases plus 5 follow-ups through the full Ask graph, checked against the independent labels. Results `eval/results/investigation_deepseek.json`; report `eval/reports/investigation_report.md`.

| Check | Result | Target (SC-08) |
|---|---|---|
| Routing (playbook, period, state exact; no investigation when none applies) | **15/15** | — |
| Narration numbers all traced to the findings | **13/13** | all cases — met |
| Verdict equals the independent label | **13/13** | — |
| Top driver agrees, positive cases | **9/9** | ≥ 90% — met |
| Negative controls report nothing notable | **4/4** | all — met |
| Narrations with no warning | 9/13 with the original lint; **13/13** after the fix below | — |
| Follow-ups kept the inherited scope / answered correctly | **5/5** / **5/5** | — |
| Planted anomalies | not run (M7 part 2) | 2/2 |
| Cost | $0.0084 for 20 questions | — |

**Checker false positive found and fixed (after the run, with a regression test):** all four low-review narrations carried the caveat "associations with delivery outcomes, not proof of cause", and the causal lint flagged the word "cause". A negated noun ("not … cause", "no … causation", up to three words apart) is now treated as a disclaimer; "because", "caused", "drove" and the other claim forms are still flagged, also in the same sentence. `eval/run_investigation_eval.py --recheck` re-applied the lint to the stored narrations without model calls: exactly these four warnings cleared; the original warnings stay in the results JSON as `warnings_at_run`. The regeneration decisions during the run were made by the original lint: all four review narrations were regenerated once (3 calls instead of 2), most likely because of this false positive, and the disclaimer survived the regeneration. Cost of the false positive: about $0.001 and 2-3 s per case.

**Tests (actually run):** full suite 543 passed, 0 skipped (1 new regression test); ruff clean on the changed files.

**API cost:** this run $0.008447. Project total **$0.054571 of the $1.90 cap** (ledger $0.053882 + calibration $0.000689).

## 2026-10-16 — M7 part 1: Investigate mode (no spend)

**Completed**
- `src/orderintel/playbooks/base.py`: typed parameters (month inside the data, valid state), placeholders substituted into the syntax tree as literals (no string formatting), then the normal validator and executor. All 19 playbook SQL steps pass the validator (the M4 scaffold test now runs).
- `late_delivery_diagnosis`: KPI vs baseline, stage decomposition, geography (states ranked by excess late orders over their own baseline), categories (≥ 30 orders), seller concentration, review impact; verdict and top driver computed in code.
- `low_review_diagnosis`: 1-star share and average score vs baseline, 1-star contribution by delivery group (late, on time, not delivered), worst categories and sellers (≥ 30 orders).
- `prompts/narrate_v1.md`, `src/orderintel/agent/narrate.py`: the model narrates the findings; checks for number grounding, top-driver agreement, and causal wording, with one regeneration.
- `src/orderintel/agent/session.py`: session scope (2-hour TTL, in memory) set by investigations, inherited by follow-up routing and SQL, with a scope-presence warning; `clear`.
- Ask graph: the investigate route runs the playbook, returns a `report` component built by code, playbook steps as evidence, follow-up suggestions that inherit the scope.
- `eval/label_investigations.py` → `eval/golden/investigation_labels.yaml`: expected verdicts and drivers computed from raw tables, independently of the views and playbooks.
- `eval/run_investigation_eval.py`: 15 cases plus 5 follow-ups with raw-table references; writes `eval/reports/investigation_report.md`.

**PRD Example 3 (T-7.7)** reproduced by the playbook: 19.0% (1,328 of 7,003) vs 5.8%; handling 3.33 vs 3.19, transit 12.97 vs 9.06, promised 22.03 vs 23.78 days; top driver carrier transit; RJ 34.5% (n = 864, baseline 10.5%); top-5 sellers 11.5% of late orders; reviews 2.07 vs 4.21, 1-star 59.3% vs 7.9%. Two figures corrected in PRD v1.7: 466 sellers (not 465; three independent definitions agree), and the state list, now ranked by excess late orders (RJ +208, SP +158, MG +147); the earlier RJ/BA/MG matched no stated rule.

**Independent labels (13 playbook cases):** 9 elevated, all drivers as computed by the playbooks (5 late-delivery: carrier transit; 4 low-review: late delivery); 4 nothing notable: the 3 planned negative controls plus December 2017 (7.46% vs 6.75%, below the pre-set +3-point rule; the M3 draft had guessed it as a positive). The case mix is reported as labelled rather than changing the rule.

**Grounding weaknesses found and fixed (measured with 200 random invented percentages, 1-40%)**
- Narration: allowing every pair among about 40 findings numbers let 166/200 invented percentages pass. Now only related pairs (a value and its own baseline, late vs on time, group rate vs group baseline): 36/200 pass. Found by a test with a deliberately invented 21.4%.
- Ask mode: on a 20-month series, all-pairs derivations let 67/200 pass; long columns now allow only adjacent, first/last, and max/min comparisons: 39/200. Single values: 0/200; top-5 table: 29/200. All 56 stored M6 answers still fully traced under the stricter rule (`--recheck`, no model calls).
- Known limit: grounding is strong for small results and weaker for long series, where invented numbers can coincide with real ones.

**Process slip, corrected:** the formatter was run on all of `src/`, which reformatted two unrelated files (`evaluation/compare.py`, `evaluation/golden.py`); both were restored from the last commit (formatting-only changes, verified by diff).

**Tests (actually run):** full suite 542 passed, 0 skipped; new: 6 investigation and scope-inheritance end-to-end tests with a fake model (playbook + grounded narration; wrong driver + invented number + causal wording regenerated then flagged; negative control; follow-up inherits the scope; follow-up that drops it is flagged; cleared and other sessions inherit nothing).

**API cost incurred in this part:** $0.00.

## 2026-10-16 — M6 part 2: Ask evaluation (owner-approved)

Run at 12:03 UTC (off-peak): all 60 golden items (both splits; measured, not tuned) plus PRD Examples 1 and 2 through the full Ask graph. Results `eval/results/ask_all_deepseek.json`; report `eval/reports/ask_eval.md`.

| Metric | Result | Target |
|---|---|---|
| SC-07 routing | **60/60 = 100%** (CI 94-100%); all 6 out-of-scope requests refused, all 54 others answered | ≥ 90% — met |
| SC-06 faithfulness (no untraced number after ≤ 1 regeneration) | **55/56 = 98%** with the original checker; **56/56** after fixing a checker false positive (below) | ≥ 95% — met |
| Faithful on the first try | 51/56; the one regeneration fixed the other 4 | — |
| Causal wording left in answers | 1/56 with the original lint (a false positive); 0/56 after the fix | 0 |
| SQL correct among answered golden items | 49/54; the same five items as the M5 configuration D runs | — |
| SC-10 latency, full Ask | p50 **2.8 s**, p95 **4.8 s** | p95 ≤ 20 s — met |
| Cost | $0.0148 for 62 questions: answers about $0.00026 (3.1 calls, one served from the M5 cache), refusals about $0.00007 | — |

**PRD examples:** Example 1 ("Top 5 categories by revenue in 2017") reproduced the figures (bed_bath_table R$497,971, watches_gifts R$486,519, health_beauty R$481,143, sports_leisure R$447,547, computers_accessories R$400,491) as a table plus bar chart, scope 2017-01-01 to 2017-12-31 with the revenue and sale definitions. Example 2 ("How is the late-delivery rate trending?") gave a line chart and named the November 2017 and February/March 2018 spikes (12.4%, 14.13%, 18.96%).

**Checker false positives found and fixed (after the run, with regression tests):**
- Grounding read the leading digits of hexadecimal seller ids (`4869f7a5…`) as numbers (trap_14). Identifiers mixing letters and digits are now removed before extraction, and a number glued to letters is ignored.
- The causal lint flagged "months were excluded because data there is sparse" (ambig_05). Sentences explaining a methodological choice (excluded, included, filtered, omitted, removed, not shown) are now skipped.
- `eval/run_ask_eval.py --recheck` re-ran the corrected checkers on all 56 stored answers without model calls: exactly these two items changed; nothing else did. The report shows both the original and the re-checked figures. The regeneration decisions during the run were made by the original checkers.

**Decisions**
- T-6.5: the anchor date and the minimum-volume rule are enforced by the prompt rules, the glossary, and the validator (real-date functions rejected with a hint). Measured: trap_12 ("last month" = July 2018) and trap_06 (≥ 30 orders) answered correctly.
- T-6.6: router and SQL generation stay separate. A refusal costs about $0.00007 and 1.3 s because it never loads the schema; merging would save about one call per answer but put the full schema into every refusal and couple two prompts. Latency is far below the target either way.

**API cost:** this run $0.014838. Project total **$0.046124 of the $1.90 cap** (ledger $0.045435 + calibration $0.000689).

**Tests (actually run):** full suite 518 passed, 1 skipped.

## 2026-10-16 — M6 part 1: Ask mode (no spend)

**Completed**
- Q-05 resolved: LangGraph 1.2.15; `StateGraph`, `START`/`END`, and `add_conditional_edges` with a path map behave as the design assumed (checked on the installed package).
- `prompts/router_v1.md`, `src/orderintel/agent/router.py`: four routes; Pydantic validation (route and playbook enums, month inside 2016-09..2018-10, valid Brazilian state); any invalid reply becomes `clarify` (FR-02).
- `src/orderintel/agent/scope.py`: period from the SQL's date comparisons (exclusive upper bounds converted, `extract(year)` handled, whole data window otherwise); definitions applied from the columns used; partial-month warnings from `data_coverage`; output component by result shape (answer card, line chart, table, bar chart for ≤ 8 groups).
- `prompts/answer_v1.md`, `src/orderintel/agent/answer.py`: answer writer (≤ 50 rows to the model; tables and charts rendered by code).
- `src/orderintel/agent/grounding.py`: number grounding (cells at displayed precision, abbreviations such as R$498k, shares, differences, ratios, percentage changes, question and scope numbers, small integers, trailing-zero roundings) and a causal-language lint.
- `src/orderintel/agent/ask.py`: LangGraph wiring of plain node functions: route → SQL (config D path: validator, executor, ≤ 2 repairs) → answer writer → grounding + lint, with one regeneration; failures and refusals return no fabricated answer. Investigate is a placeholder until M7.
- `src/orderintel/api/schemas.py`: response contract (technical design section 9).
- `eval/run_ask_eval.py`: routing (SC-07), faithfulness (SC-06), SQL correctness of answered items, latency (SC-10), cost; writes `eval/reports/ask_eval.md`.

**Tests (actually run):** full suite 515 passed, 1 skipped; new: 13 router, 22 grounding/lint, 12 scope/component unit tests; 10 end-to-end Ask tests with a role-aware fake model (grounded answer; one regeneration fixes an untraced number; a persistent one becomes a visible warning; causal wording flagged; refusal and invalid router reply run no SQL; SQL failure after repairs gives no answer; declined SQL; investigate placeholder; line chart and partial-month warnings).

**Decision (T-6.6, provisional until measured):** router and SQL generation stay separate calls. The router prompt is small and needs no schema, so a separate call is cheap; merging would put the whole schema into every refusal. Revisited after the paid run with measured cost and latency.

**Deferred:** request-level trace rows (`trace.requests` currently holds one row per LLM call, which the budget guard uses); the request/step trace recorder is wired in M9 (T-9.2).

**API cost incurred in this part:** $0.00.

## 2026-10-16 — M5 part 4: the single test-split run (headline result, owner-approved)

Run once at 11:19 UTC with the selected prompt `sqlgen-v1`, after confirming the test-split fingerprint was unchanged (`c8262a28…`). 18 answerable test items. Results `eval/results/test_*_deepseek_sqlgen-v1.json`; manual review `eval/reviews/test_sqlgen-v1_tags.yaml`; report `eval/reports/ablation.md`.

| Config | Strict correct (95% CI) | Data correct after review | Real analytical errors |
|---|---|---|---|
| A raw DDL | 3/18, 17% (6-39%) | 5/18 | 13 |
| B + glossary | 15/18, 83% (61-94%) | 17/18 | 1 (duplicate reviews, lookup_07) |
| C views + glossary | 15/18, 83% (61-94%) | 17/18 | 1 (payment types, trend_08) |
| D C + controls | 15/18, 83% (61-94%) | 17/18 | 1 (same as C) |

**Success criteria (PRD section 12) — Q-06 resolved, targets not revised**
- SC-04 (D ≥ 75% on the test split and ≥ 15 points above A): **met on the point estimate** (83%, +66 points). With 18 items the 95% interval (61-94%) still includes values below 75%, so the claim is "met, with wide uncertainty".
- SC-05 (traps ≥ 70% for D): test 4/5; development 9/9; combined 13/14 (93%, CI 69-99%). **Met.**
- SC-10 (latency): SQL generation alone has p50 about 1.2 s and p95 about 2.1 s; the full Ask p95 is measured in M6.

**What the measurements say (reported as measured, including negative results)**
1. The glossary is the largest single gain: A → B is +66 points on the test split (+28 on development). A's errors are the documented data traps: freight counted as revenue (5), lateness by timestamp (3), missing filters (2), duplicate reviews (1), partial months (1).
2. The views add no strict accuracy over the glossary on the test split (B = C = 83%); on development C was +8 points over B with `sqlgen-v1`, and +-2 with `sqlgen-v2`. With 18-36 items this difference is within noise. B and C each made one real error, and different ones.
3. The views introduced one error of their own: the `payments` view's one-row-per-order design (which prevents fan-out) exposes `primary_payment_type`, and C counted orders by it instead of counting every type an order used (trend_08). A design trade-off to address in a later view revision (for example per-type boolean columns); it cannot be re-scored on the test split without contaminating it.
4. D equals C: across all D runs the validator and executor rejected nothing, so no repair was ever used. On these questions the controls add safety, not accuracy; the repair loop is exercised only by the fake-model tests and the safety suite (M8).
5. A scored much lower on test (17%) than on development (58%): the test items happen to contain more definition traps (freight, lateness, canceled orders) and fewer pure lookups.
6. Cost per question (SQL generation): about $0.0001 off-peak with prompt caching.

**API cost:** test run $0.006299. Project total **$0.031286 of the $1.90 cap** (ledger $0.030597 + calibration $0.000689).

## 2026-10-16 — M5 part 3: prompt iteration `sqlgen-v2` (owner-approved) and prompt selection

`sqlgen-v2` (`prompts/sqlgen_rules_v2.md`) added output-shape rules: no helper columns, one row/one column for single values, boolean labels for yes/no groups, months as dates. Rerun of A to D on the development split at 11:11 UTC; manual review in `eval/reviews/dev_sqlgen-v2_tags.yaml`.

| Prompt | A | B | C | D | C/D data correct after review |
|---|---|---|---|---|---|
| `sqlgen-v1` | 21/36 | 31/36 | 34/36 | 34/36 | 36/36 |
| `sqlgen-v2` | 21/36 | 34/36 | 32/36 | 32/36 | 36/36 |

- v2 fixed the earlier format misses (extra count columns, text labels) but caused new ones in C and D: years labelled as dates (`2017-01-01` instead of `2017`) and supporting values dropped ("biggest market" returned only `SP`). B gained 3 (its format misses disappeared); its two real errors remain.
- With either prompt, C and D made no analytical errors; only format compliance moved.
- **Decision:** iteration stopped after 2 of the 3 allowed rounds, because further rules would fit the prompt to the exact shape of 36 development references. Final prompt chosen by a rule fixed before any test run: highest strict accuracy of configuration D on the development split → **`sqlgen-v1`** (34 vs 32). Recorded in `eval/reviews/prompt_selection.yaml`, including the trade-off that v2 favoured B.
- Result files now include the prompt version (`eval/results/dev_<config>_deepseek_<prompt>.json`); the report shows the iteration history and the selected prompt.

**Cost:** this run $0.011667. Project total: **$0.024987 of the $1.90 cap** (ledger $0.024298 + calibration $0.000689).

## 2026-10-16 — M5 part 2: first ablation run, development split (owner-approved)

Run at 11:00 UTC (off-peak), `deepseek-flash`, thinking disabled, temperature 0, prompt `sqlgen-v1`; 36 answerable development items. Results: `eval/results/dev_{A,B,C,D}_deepseek.json`; report: `eval/reports/ablation.md`; manual review: `eval/reviews/dev_sqlgen-v1_tags.yaml`.

| Config | Strict correct (95% CI) | Data correct after manual review | Real analytical errors | Cost |
|---|---|---|---|---|
| A raw DDL | 21/36, 58% (42-73%) | 22/36 | 14 | $0.0042 |
| B + glossary | 31/36, 86% (71-94%) | 34/36 | 2 | $0.0048 |
| C views + glossary | 34/36, 94% (82-98%) | 36/36 | 0 | $0.0037 |
| D C + validator + repairs | 34/36, 94% (82-98%) | 36/36 | 0 | $0.0000 (all 36 served from C's cache) |

**What the run shows**
- A's errors are the documented data traps: revenue with freight or canceled orders (5), lateness by timestamp (4), duplicate reviews (2), delivered-only "sales" (1), no minimum volume (1), partial months in a trend (1).
- The glossary (A → B, +28 points strict) removes most definition errors; the views (B → C, +8 points) remove the rest (B still had one item-level fan-out and one duplicate-review error).
- C's two misses are format only (extra count columns; `'late'`/`'on_time'` labels instead of a boolean): the numbers are right.
- D equals C on the development split: the validator rejected nothing, so no repair was needed, and D's identical first request came from the cache. D's contribution is safety, not accuracy, on these questions; this is a negative result to report as measured.
- p50 latency about 1.2-1.3 s, p95 about 1.8-2.1 s per question (SQL generation only).

**Caveats:** 36 items; confidence intervals overlap between B, C, and D. The development split may be used for tuning, so these numbers are not the headline result; the frozen test split is.

**Cost:** this run $0.012631 (ledger and results agree). Project total: **$0.013320 of the $1.90 cap** ($0.000689 calibration + $0.012631 this run; the calibration ran before the ledger existed, so the guard counts slightly less than the true total).

## 2026-10-16 — M5 part 1: LLM client, prompts, ablation runner (no spend)

**Completed**
- `src/orderintel/llm/`: `pricing.py` (DeepSeek peak/off-peak prices, usage parsing for both providers, worst-case cost), `budget.py` (ledger in `trace.requests` via `oi_trace`; guard checks total $1.90 / daily $0.40 caps and Gemini RPM/RPD before every call), `cache.py` (SHA-256-keyed response cache in git-ignored `eval/cache/llm/`), `client.py` (one client for both providers; thinking disabled for DeepSeek; at most two retries on 429/503/connection errors; dry-run; pluggable transport).
- `prompts/sqlgen_rules_v1.md` and `src/orderintel/agent/sqlgen.py`: configurations A (raw DDL, comments stripped), B (A + glossary definitions without view references), C/D (view documentation + full glossary). Rules first, question last, so the provider's prefix cache applies.
- `src/orderintel/agent/pipeline.py`: A to C run unvalidated SQL as read-only `oi_eval` (timeout, row cap); D uses validator + executor + at most two repairs with the rejection reason fed back.
- `src/orderintel/evaluation/ablation.py`, `stats.py`, `eval/report.py`: scoring against references and accepted alternatives, Wilson 95% intervals, per-category results, repairs, cost, p50/p95 latency, automatic failure-tag suggestions; `eval/reports/ablation.md`.
- `eval/run_eval.py --config ... --split ... [--estimate] [--approved] [--confirm-test]`: refuses paid calls without `--approved` and the frozen test split without `--confirm-test`.

**Tests (actually run):** full suite 460 passed, 1 skipped (playbook scaffold); new: 16 client/pricing/budget/cache tests, 17 prompt tests, 10 end-to-end fake-model pipeline tests (including D repairs after a validator rejection, bad JSON, and the cost ceiling; repair cap; a fake model answering with reference SQL scores 5/5), ledger integration test. The cost formula reproduces the calibration measurement ($0.000319). Lint and secret scan pass (the scanner caught a key-shaped fake test key, which was renamed).

**Cost estimates (before any paid run):** development split, all four configurations: expected $0.017, worst case $0.38; test split, once each: expected $0.009, worst case $0.19.

**API cost incurred in this part:** $0.00.

## 2026-10-16 — M0b: DeepSeek calibration

**Completed:** owner added the DeepSeek key (checked for format only, never printed) and approved 10 calls; `scripts/calibrate.py --provider deepseek` ran at 10:38 UTC (off-peak). Results in `docs/provider_facts.md`.

**Results (actually observed)**
- 10 of 10 calls succeeded; latency 0.7-1.5 s (`deepseek-flash`), 2.45 s (`deepseek-v4-pro`).
- Thinking disabled works (no reasoning tokens); a control call without the parameter produced 20 reasoning tokens.
- Automatic prompt caching: 1,664 of about 1,860 prompt tokens hit the cache on later SQL calls, making them about three times cheaper.
- All four SQL answers to development questions validated, executed, and matched the references (agg_10 twice, trend_01, agg_04 within tolerance).
- Usage field names recorded for the ledger (Q-02 answered).

**Decision taken (owner-approved):** both DeepSeek and Gemini restricted an "overall" late rate to January 2017-August 2018 (6.79%) while the reference uses all data (6.77%). Glossary v1.1 and PRD v1.6 now state that the window applies to trends, monthly series, month-to-month comparisons, and per-month averages, and not to totals or "overall" figures. The rule was checked against the frozen references (agg_01/02/04/09 use all data; trap_11 uses all of 2016; trap_07 averages only January-August 2018; ambig_05 uses the window), so no golden item changed and the test-split fingerprint is unaffected. This is a definition fix, not prompt tuning on test questions.

**API cost incurred:** $0.000689 (DeepSeek, off-peak). Total project spend so far: **$0.000689 of the $1.90 cap.** Gemini: 11 requests, $0.

## 2026-10-16 — Provider: back to DeepSeek, Gemini kept as second provider

**Why:** the owner completed the DeepSeek top-up.

**Changes:** PRD v1.5, technical design v1.6, and implementation plan v1.4 restore the DeepSeek design (US$2 budget, `deepseek-flash` / `deepseek-v4-pro`) from the pre-switch versions in git and add: the verified thinking switch (`extra_body={"thinking": {"type": "disabled"}}`; default is on at `high` effort; thinking mode ignores `temperature`), Gemini free tier as the optional second provider (F-16, T-10.7), and bounded retries on 429 and 503. `.env.example` now holds both providers with `LLM_PROVIDER=deepseek`; the local `.env` was rebuilt from it, keeping all existing values (none printed). `scripts/calibrate.py` takes `--provider deepseek|gemini`. The Gemini calibration results below remain valid for the second provider.

## 2026-10-16 — M0b: provider calibration (Gemini free tier)

**Completed**
- Owner created a Gemini key in a project without billing; free-tier limits recorded from AI Studio (`gemini-3.5-flash-lite`: 15 RPM, 250K input TPM, 500 RPD). Caps set in `.env` and `.env.example`: 12 RPM, 200K TPM, 450 RPD.
- One connectivity test call, then 10 owner-approved calibration calls (`scripts/calibrate.py`).
- `docs/provider_facts.md` written (Q-02 answered except the comparison model's limits).

**Results (actually observed)**
- Warm latency 1.1-1.9 s; cold first call 11.4 s; realistic SQL-generation call 1.2 s at thinking `low`.
- Thinking cannot be disabled (`none` → HTTP 400); `minimal`/`low` accepted. Thinking tokens are not reported separately but equal total − prompt − completion: 0 at `low`, 1,028 at `medium` (+3.3 s).
- JSON schema and JSON object outputs work.
- `gemini-3.8-flash` returned HTTP 503 (high demand): the client must retry 503 and 429 with bounded backoff.
- Two development questions answered by the model: both validated and executed; both scored correct, but one (overall late rate) applied the analysis window on its own and passed only within the rounding tolerance.

**Decisions and open issues**
- Default thinking level `low`; thinking tokens derived from `total_tokens`.
- Before M5: clarify in the glossary when the analysis window applies (totals vs trends), so model and references use the same scope.
- Known comparer limitation: a 0.02-point scope difference on a percentage passes the tolerance; such cases are tagged manually in M5 review.
- Still to record: `gemini-3.8-flash` free-tier limits and one successful call.

**API usage:** 11 requests, about 7,500 tokens, **$0.00 billed** (notional paid-tier cost under $0.01).

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
