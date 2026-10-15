# Product Requirements Document: Order Intelligence Agent

| Field | Value |
|---|---|
| Version | 1.2 |
| Date | 2026-10-15 |
| Author | Sai Charan Kukkala |
| Related documents | [TECHNICAL_DESIGN.md](TECHNICAL_DESIGN.md), [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) |

## 1. Overview

Order Intelligence Agent is a natural-language analytics assistant for an e-commerce marketplace. A user asks a question about orders, deliveries, sellers, payments, or customer reviews. The system either answers it with a validated, read-only SQL query, investigates it with a tested analysis playbook, asks a clarifying question, or declines. Every response shows the definitions applied, the queries executed, the rows behind each figure, and the caveats.

The system is built on the public Olist Brazilian E-Commerce dataset (about 100,000 anonymised orders, 2016–2018).

The project is designed around verifiable behaviour rather than demo polish:

- The agent cannot modify or escape the database, even if the language model misbehaves. Safety is enforced by database permissions and deterministic code, not by prompts.
- SQL accuracy is measured on a golden question set, with ablations that isolate the contribution of each design element.
- Every number in an answer is traceable to a query result.
- The whole system, including evaluation, is built within a US$2 LLM API budget.

## 2. Problem statement

Business users have operational questions such as "why did deliveries slip in Rio last March?". The data sits in a relational database whose quirks silently produce wrong numbers when queried naively. Answering requires an analyst who writes SQL, remembers the data traps, and runs several queries for any "why" question.

| Alternative | Limitation |
|---|---|
| Hand-written SQL | Effective for experts, but not self-service. Business definitions such as "late" get re-implemented inconsistently. |
| General-purpose chatbot | Has no access to the data and produces plausible but unverifiable numbers. |
| Fixed dashboard | Good for recurring KPIs. Every new question needs an analyst, and it cannot explain causes. |
| This system | Free-form questions, business definitions encoded once, auditable evidence for every number, and repeatable investigations for "why" questions. |

The system is not a dashboard replacement and not a full BI tool. It provides conversational analysis with evidence.

## 3. Target users

**Primary user:** a marketplace operations or seller-success analyst who needs reliable numbers quickly but does not know the schema or its pitfalls.

**Secondary audience:** engineers and reviewers evaluating the repository. The repository must communicate its design, measured results, and limitations through the README, an architecture diagram, evaluation reports, and a short demo video.

## 4. Goals and non-goals

### Goals

- G1. Answer free-form questions about the data with auditable evidence.
- G2. Investigate two diagnostic questions (late deliveries, low review scores) with findings computed in code and honestly caveated.
- G3. Enforce safety through database roles and deterministic validation.
- G4. Measure accuracy (with ablations), answer faithfulness, safety, latency, and cost, and report results as measured.
- G5. Keep total LLM API spend within US$2, including evaluation.
- G6. Be reproducible: a clean clone reaches a working application by following the README.

### Non-goals (version 1)

- Forecasting or prediction.
- Any write operation against the data.
- Maps or geolocation questions. The geolocation table is not loaded.
- Review-text analysis. Review text is excluded from the model's context.
- User accounts or multi-tenant access. The deployment is single-user.
- Real-time or streaming data. The dataset is static history.
- Causal claims. Findings describe associations in observational data.
- Claims about scale. About 100,000 orders is a small dataset.

## 5. Dataset

### 5.1 Source and tables

The system uses the Olist Brazilian E-Commerce Public Dataset (nine CSV files from Kaggle). The files are downloaded manually and are not committed to the repository.

| Table | Rows | Used in v1 |
|---|---|---|
| orders | 99,441 | Yes. Order status and five timestamps. |
| order_items | 112,650 | Yes. Price, freight, seller, product. |
| order_payments | 103,886 | Yes. Several rows per order are possible. |
| order_reviews | 99,224 | Yes, scores and dates only. Comment text is excluded. |
| customers | 99,441 | Yes. |
| products | 32,951 | Yes (category and weight). |
| sellers | 3,095 | Yes. |
| product_category_name_translation | 71 | Yes. |
| geolocation | 1,000,163 | No. |

The files contain no name, email, or phone columns.

### 5.2 Data window

Purchases span 2016-09-04 to 2018-10-17, with very uneven volume. Only three months of 2016 are present (4, 324, and 1 orders), and September and October 2018 contain 16 and 4 orders. The analysis window is **January 2017 to August 2018**. The system treats **2018-08-31** as "today" when resolving relative dates. Months with fewer than 500 orders are reported with a partial-period warning.

### 5.3 Data quality findings and how the system handles them

All dataset figures in this document (here and in section 8.3) are provisional until reproduced by the project's own queries: counts in M1, semantic-layer figures in M2, and investigation figures in M7. Any difference is corrected here and recorded in the document history.

| Finding | Evidence | Handling |
|---|---|---|
| Join fan-out on payments | 2,961 orders have multiple payment rows. Joining items to payments naively inflates item revenue by 4.54% (13.59M to 14.21M). | `payments` view with one row per order. Golden-set trap questions. |
| Customer identity | `customer_id` is per order (99,441 values); distinct people number 96,096. Only 2,997 customers placed more than one order (about 3%). | Use `customer_unique_id`. Retention questions are answered with the actual, low repeat rate. |
| Ambiguous "late" | `estimated_delivery_date` is always midnight. Comparing timestamps marks 1,292 same-day deliveries as late: 8.11% overall, versus 6.77% when comparing dates. | Late is defined by date comparison (section 6). |
| Undelivered orders | 2,965 orders have no customer delivery date (2,957 non-delivered orders plus 8 "delivered" orders); 6 non-delivered orders have one. 2,963 orders are not in `delivered` status. | Late is defined only for delivered orders with a delivery date. |
| Duplicate reviews | 814 repeated `review_id` rows; 547 orders have more than one review; about 5% of reviews pre-date the recorded delivery date. | `reviews` view: latest answered review per order. |
| Category gaps | 610 products have no category; 2 categories have no English translation. | Left joins, with `unknown` as the label. |
| Small sellers | The median seller has 6 orders; 1,301 of 3,095 sellers have fewer than 5; 51 sellers with 1 to 3 delivered orders show a 100% late rate (late by date; the timestamp comparison would give 57). | Ranking eligibility requires at least 30 orders (634 sellers, 76.8% of revenue). |
| Multi-seller orders | 1,278 orders involve more than one seller. | Order-level outcomes are never attributed to a single seller without stating so. |
| Sparse months | See section 5.2. | Partial-period warnings from a coverage view. |
| Untyped source | All CSV fields are text. | Typed tables created at load time. |

## 6. Business definitions

These definitions are versioned in `glossary/glossary.md`, supplied to the model, and displayed to users in the scope panel.

| Term | Definition |
|---|---|
| Delivered order | `order_status = 'delivered'` and a customer delivery timestamp exists. |
| Late | Delivered date is later than the estimated delivery date. Dates are compared, not timestamps. |
| On time | A delivered order that is not late. |
| Sale / revenue | Sum of item `price`, excluding freight, over orders whose status is not `canceled` or `unavailable`. Including those orders changes 2017 revenue by 0.77%. |
| Customer | `customer_unique_id` (a person), never `customer_id`. |
| Order month | Month of the purchase timestamp. |
| Seller handling days | Carrier hand-off timestamp minus purchase timestamp. |
| Carrier transit days | Customer delivery timestamp minus carrier hand-off timestamp. |
| Promised days | Estimated delivery date minus purchase timestamp. |
| Review score | Score of the latest answered review for the order. |
| Ranking eligibility | A seller or group needs at least 30 orders to appear in a ranking. The sample size is always shown. |
| Baseline (diagnosis) | The pooled value over all other months in the analysis window, excluding the period under investigation. Spike months slightly inflate the baseline, which makes findings conservative. |
| Partial period | A month with fewer than 500 orders. |

## 7. Scope

### 7.1 Features

| ID | Feature | Priority |
|---|---|---|
| F-01 | Ask mode: question to validated SQL to result with evidence | Must |
| F-02 | Semantic layer: curated views and business glossary | Must |
| F-03 | Layered SQL safety: database role, validator, resource limits | Must |
| F-04 | Number grounding: every number in prose traced to results | Must |
| F-05 | Router: answer, investigate, clarify, or refuse | Must |
| F-06 | Evidence-first UI: four result components and a trace panel | Must |
| F-07 | Golden-set evaluation with ablations | Must |
| F-08 | Safety test suite, including an injection test using review-style text | Must |
| F-09 | Request tracing and cost ledger with hard budget caps | Must |
| F-10 | Investigate mode: two playbooks and follow-up scope inheritance | Should |
| F-11 | Model comparison (two DeepSeek models on a subset) | Should |
| F-12 | Continuous integration for deterministic tests | Should |
| F-13 | Local setup, README, and architecture diagram | Must |
| F-14 | AWS deployment and demo video | Should |
| F-15 | Seller-scoped mode using row-level security | Could |
| F-16 | Second model from another provider | Could |

### 7.2 Out of scope

Watch/monitoring mode, human approval flows, a hash-chained audit log, document retrieval (RAG), maps, forecasting, multi-user authentication, fine-tuning, and multi-agent orchestration.

## 8. User experience

### 8.1 Interaction model

The interface has a single text input. The system selects a route and renders one or more of four components:

| Component | Used when |
|---|---|
| Answer card | A single value or short statement. |
| Table | A ranking or a lookup list. |
| Chart (line or bar) | A time series or a comparison across a few groups. |
| Report | An investigation: headline, findings, caveats, evidence. |

Every response also carries a **scope panel** (period, definitions applied, filters, sample size, assumptions, partial-period warnings), an **evidence panel** (SQL, parameters, row preview, validation result, per-step latency), **follow-up suggestions**, and a cost and latency line.

The output component is chosen by deterministic rules on the shape of the result: one row gives an answer card; a time series gives a line chart; ranked categories give a table (a bar chart when there are eight or fewer groups); an investigation gives a report. The model may suggest a format but does not decide it.

### 8.2 Special behaviours

| Situation | Behaviour |
|---|---|
| Ambiguous question | Asks one clarifying question, or states its assumption in the scope panel and answers. |
| Out of scope, destructive, or predictive request | Declines with a reason. No SQL is executed. |
| Period includes a partial month | Warning in the scope panel. |
| Empty result | States that no rows matched and shows the filters applied. |
| Validation or timeout failure after retries | Reports the failure and the attempted SQL. No answer is fabricated. |
| Budget exhausted | Displays a budget message. Cached answers remain available. |
| Number cannot be traced to evidence | The answer is shown with a visible warning. |

### 8.3 Example interactions

Figures below were computed from the Olist dataset under the definitions in section 6 and are reproduced by acceptance tests (see the implementation plan, milestones M2 and M7).

**Example 1. "Top 5 categories by revenue in 2017"** (table with headline)

```
bed_bath_table led 2017 with R$498k (8.2% of item revenue).
The top three are within about 3.4% of each other, so the ranking is sensitive to the definition.

 category               revenue    share   orders
 bed_bath_table         497,971    8.2%    4,496
 watches_gifts          486,519    8.0%    2,114
 health_beauty          481,143    7.9%    3,382
 sports_leisure         447,547    7.3%    3,621
 computers_accessories  400,491    6.6%    2,606

Scope: revenue = item price excluding freight; canceled/unavailable orders excluded
(including them changes the total by 0.8%); year by purchase date;
total R$6.11M across 44,375 orders. Currency assumed to be BRL.
[View SQL] [View rows]   Validated, read-only, 1 query
```

**Example 2. "How is the late-delivery rate trending?"** (line chart)

Monthly late rate, January 2017 to August 2018 (%): 2.9, 3.0, 4.6, 6.6, 3.0, 3.0, 2.8, 2.9, 4.4, 4.2, **12.4**, 7.5, 5.7, **14.1**, **19.0**, 4.5, 6.6, 1.2, 3.4, 6.2. The chart annotates the spikes in November 2017, February 2018, and March 2018. A note states that 2016 and September–October 2018 are omitted (fewer than 500 orders per month) and that late means delivered date after estimated date, for delivered orders only. Follow-up suggestions: "Investigate March 2018" and "Break down by state".

**Example 3. "Why was March 2018 so bad for deliveries?"** (investigation report)

```
HEADLINE  19.0% late (1,328 of 7,003 delivered orders) versus a 5.8% baseline.
          The extra time was lost in carrier transit, not seller handling, and it was broad.

1 WHERE TIME WAS LOST   average days   Mar    baseline
                        seller          3.3     3.2
                        transit        13.0     9.1   (+3.9 days)
                        promised       22.0    23.8   (estimates were not extended)
2 GEOGRAPHY             RJ 34.5% late (n=864; baseline 10.5%)
                        BA 31.5% (n=235; baseline 10.7%)
                        MG 20.4% (n=856; baseline 3.3%)
                        Excluding RJ and BA the rate is still 16.2%: the pattern is systemic.
3 SELLER CONCENTRATION  465 distinct sellers among late orders; the top 5 account for 11.5%.
4 CUSTOMER IMPACT       average review 2.07 (late, n=1,296) versus 4.21 (on time, n=5,652);
                        1-star share 59.3% versus 7.9%.
CAVEATS   The data shows where delay occurred, not why the carrier slowed.
          November 2017 (12.4%) and February 2018 (14.1%) were also elevated; seasonality is possible.
          Lateness accounts for only about 30% of all 1-star reviews in the dataset.
EVIDENCE  All queries validated; every number traced.
FOLLOW-UP "Which RJ sellers were slowest?" (inherits: March 2018, RJ, delivered orders)
```

### 8.4 Comparison with alternatives

| | General chatbot | Fixed dashboard | This system |
|---|---|---|---|
| New question | Answers, but invents numbers | Requires an analyst | Runs a validated query |
| Trust | Nothing to inspect | Fixed, trusted query | SQL, rows, definitions, and caveats shown |
| Format | Prose | Pre-built charts | Chosen from the result shape |
| "Why?" questions | A plausible story | Not supported | Computed evidence with caveats |

## 9. Functional requirements

Priority follows MoSCoW. "Verification" names the test level that demonstrates the requirement.

| ID | Requirement | Priority | Verification |
|---|---|---|---|
| FR-01 | The system shall accept a natural-language question and return a structured response (see the technical design, section 9). | Must | API contract test |
| FR-02 | The router shall return JSON with `route` in {answer, investigate, clarify, refuse}; invalid output shall default to `clarify`. | Must | Unit test, eval |
| FR-03 | Ask mode shall generate a single SELECT statement over the `analytics` views only. | Must | Validator unit tests |
| FR-04 | All SQL, whether generated or from a playbook, shall pass the validator and a single executor. No other path to the database shall exist. | Must | Integration test |
| FR-05 | The executor shall use a read-only role, a statement timeout, a row cap, and an EXPLAIN cost ceiling. | Must | Integration test |
| FR-06 | The system shall make at most two repair attempts after a validation rejection or execution error. | Must | Unit test with a fake LLM |
| FR-07 | The answer text shall be generated from result rows; a number-grounding check shall run; one regeneration shall be allowed; a failed check shall be shown as a visible warning. | Must | Unit test, eval |
| FR-08 | Every response shall include a scope statement: period, definitions, filters, sample size, assumptions, and partial-period warnings. | Must | Contract test |
| FR-09 | The output component shall be selected by the rules in section 8.1. | Must | Unit test |
| FR-10 | The evidence panel shall expose SQL, parameters, a row preview, the validation result, and per-step latency. | Must | UI test |
| FR-11 | Investigate mode shall run a playbook with typed, validated parameters; compute findings in code; reject narration that contradicts the findings; and lint causal language. | Should | Unit test, eval |
| FR-12 | Investigate mode shall set a session scope that follow-up questions inherit; the user shall be able to view and clear it. | Should | Eval |
| FR-13 | Rankings shall apply the minimum-volume rule and always display the sample size. | Must | Eval, unit test |
| FR-14 | Partial-period warnings shall be derived from the coverage view. | Must | Integration test |
| FR-15 | Every request shall write a trace containing steps, tokens, cost, and latency. | Must | Integration test |
| FR-16 | The budget guard shall block LLM calls beyond the configured total and daily caps. | Must | Unit test |
| FR-17 | The evaluation CLI shall run configurations over the golden set and write JSON and Markdown reports with per-category accuracy, cost, latency, and failure tags. | Must | Eval run |
| FR-18 | The safety suite shall run deterministic tests without an LLM, and LLM-involving tests under a budget cap. | Must | Safety report |
| FR-19 | The data loader shall be reproducible and shall assert expected row counts. | Must | Integration test |
| FR-20 | A public deployment shall require an access code and enforce a rate limit and a daily spend cap. | Should | Deployment smoke test |

## 10. Non-functional requirements

| ID | Requirement |
|---|---|
| NFR-01 | Security by construction: the model never holds credentials and never connects to the database; the blast radius of any model failure is bounded by database permissions. |
| NFR-02 | Cost: total LLM API spend shall not exceed US$2.00, enforced by a hard cap in code. |
| NFR-03 | Latency (initial target): p95 at or below 20 s for Ask and 45 s for Investigate. |
| NFR-04 | Reproducibility: pinned dependencies, deterministic tests, cached evaluations, and temperature 0 where available. |
| NFR-05 | Privacy: no personal data is used, and review comment text is never sent to the model in v1. |
| NFR-06 | Observability: every request is traceable end to end; logs and traces never contain secrets. |
| NFR-07 | Portability: the system runs through Docker Compose on Windows, macOS, and Linux. |
| NFR-08 | Maintainability: typed code, linting, and documentation kept consistent with the implementation. |

## 11. Evaluation approach

Details are in the technical design, section 8.

| Evaluation | Size (target) | Scoring |
|---|---|---|
| Golden set (Ask) | 60 questions: 40 development, 20 held-out test | Execution accuracy against reference SQL written on the raw tables |
| Investigation | 15 cases (6 late-delivery, 4 low-review, 3 negative controls, 2 with no applicable playbook) plus 2 planted-anomaly tests | Evidence integrity, top-driver agreement, calibration |
| Safety | At least 40 attack cases | Any success counts as a failure |
| Ablations | Configurations A to D over the same 60 questions | Accuracy deltas between configurations |

Execution accuracy is computed over the answerable items only (54: every category except out-of-scope or hostile; ambiguous items are scored against their accepted interpretations). The 6 out-of-scope items are scored only as routing (SC-07). Because the test split is small (20 items, about 18 answerable), accuracy is reported with 95% confidence intervals (Wilson), and differences of one or two items are not treated as meaningful.

Golden-set composition: lookup 8, aggregate 14, trend or comparison 12, trap 14, ambiguous 6, out-of-scope or hostile 6. The 14 trap questions cover payment fan-out, customers versus orders, the date-versus-timestamp boundary for "late", undelivered orders, missing and untranslated categories, minimum volume, partial periods, duplicate reviews, multi-seller orders, freight versus price, canceled-order exclusion, relative dates against the anchor, repeat-customer share, and an ambiguous "best seller" question.

## 12. Success criteria

The values below are initial targets. They are reviewed after the baseline evaluation (milestone M5), and any revision is recorded in the document history with its rationale. Results are reported as measured, including negative ablation results.

| ID | Criterion | Target | Evidence |
|---|---|---|---|
| SC-01 | The agent database role cannot write, alter, or read outside the curated views | 100% of at least 25 attempted statements fail | Integration test log |
| SC-02 | Attack suite | 0 of at least 40 attacks succeed | Safety report |
| SC-03 | Validator rules | All unit tests pass; each rule has positive and negative cases; runs in CI without network | CI log |
| SC-04 | Execution accuracy (configuration D, answerable items) | At least 75% on the held-out test split, and at least 15 percentage points above configuration A; reported with 95% confidence intervals | Evaluation report |
| SC-05 | Trap questions (configuration D) | At least 70% | Per-category results |
| SC-06 | Answer faithfulness | At least 95% of answers have no untraced number (after at most one regeneration) | Grounding report |
| SC-07 | Routing | At least 90% correct routes across all labelled items (counts reported) | Evaluation report |
| SC-08 | Investigation | Every number traced in 15 of 15 cases; top driver agrees in at least 90% of positive cases; 3 of 3 negative controls report no notable issue; 2 of 2 planted anomalies detected | Investigation report |
| SC-09 | Cost | Total API spend at most US$2.00; cost per question and p50 and p95 latency reported | Spend ledger |
| SC-10 | Latency | p95 within NFR-03 | Evaluation report |
| SC-11 | Reproducibility | A clean clone reaches a working application in at most 6 commands following the README | Fresh-directory run |
| SC-12 | Documentation | README with architecture diagram, ablation table, safety results, limitations, and cost; demo video of 3 minutes or less | Repository |

## 13. Cost constraints

The project is limited to **US$2.00** of LLM API spend, including all evaluation runs.

Provider pricing used for planning (DeepSeek official pricing page, retrieved 2026-10-15), per 1M tokens:

| Model | Input, cache miss (peak / off-peak) | Input, cache hit (peak / off-peak) | Output (peak / off-peak) |
|---|---|---|---|
| `deepseek-flash` | $0.30 / $0.15 | $0.006 / $0.003 | $1.20 / $0.60 |
| `deepseek-v4-pro` | $1.32 / $0.66 | $0.044 / $0.022 | $3.96 / $1.98 |

Peak hours are 01:00–04:00 and 06:00–10:00 UTC on weekdays. All other times are off-peak. The retired alias `deepseek-v4-flash` is not used; model identifiers are read from configuration. Thinking mode is the provider's default and bills reasoning tokens as output, so every call explicitly selects non-thinking mode (technical design, section 10.2). The prices and model identifiers above were re-checked against the official page on 2026-10-15.

Estimated cost per request (to be calibrated in M0 with real usage figures):

- Full Ask request (router, SQL generation, answer; about 5.5k input and 800 output tokens): about $0.002–0.003 at peak price without caching, about $0.0015 off-peak.
- Ablation runs for configurations A to C (SQL generation only; about 3k input and 300 output tokens): about $0.001 per question.
- Investigate request: about $0.005.

Cost controls are described in the technical design, section 10.3: a hard cap in code, an evaluation cache, bounded output length per call, and scheduling paid evaluation runs for off-peak hours. If measured cost exceeds twice the estimate, the number of repeated runs is reduced before any safety tests are cut.

## 14. Assumptions and dependencies

**Assumptions**

| ID | Assumption |
|---|---|
| A-01 | Free-text review comments may contain personal details; they are excluded from model context in v1. |
| A-02 | Monetary amounts are in Brazilian reais (BRL). |
| A-03 | LLM cost estimates in section 13 hold within a factor of two; this is checked in M0. |
| A-04 | Docker and Docker Compose are available on the development machine. |
| A-05 | The prepaid API balance does not expire during the project. |
| A-06 | Streamlit is sufficient to render the four result components. |
| A-07 | A 2 GB cloud instance can run the database, API, and UI together. |

**Dependencies**

The Olist dataset (manual download from Kaggle), the DeepSeek API, Docker, GitHub (CI), and AWS (deployment only).

## 15. Risks

| ID | Risk | Mitigation |
|---|---|---|
| R-01 | Silently incorrect SQL (for example join fan-out) | Curated views, trap questions, independent reference SQL on raw tables |
| R-02 | Ambiguous business definitions | Glossary, scope panel, clarify route |
| R-03 | Causal overclaiming | Association-only language lint, caveats, negative controls |
| R-04 | Prompt injection, particularly through review text | Database-level blast radius, text excluded from v1 context, dedicated injection suite |
| R-05 | Budget overrun | Hard caps, response cache, off-peak runs, measured calibration |
| R-06 | Invalid evaluation (wrong references, tuning on test data) | Development/test split, independent references, manual review of every mismatch |
| R-07 | Abuse of a paid key through a public demo | Access code, rate limits, daily cap, small balance, kill switch |
| R-08 | Scope creep | Priority tiers; Should and Could items are cut first |
| R-09 | Conclusions drawn from small samples | Minimum-volume rule; sample size always shown |
| R-10 | Tool or API drift (DeepSeek, LangGraph, AWS terms) | Pinned versions; open questions below |

## 16. Open questions

| ID | Question | Resolved in |
|---|---|---|
| Q-01 | Olist licence and redistribution terms (the CSV files are not committed) | M1, before publishing |
| Q-02 | DeepSeek API details: base URL, usage fields including cache hits, default thinking mode, rate limits, balance expiry, minimum top-up | M0 |
| Q-03 | PostgreSQL behaviours the safety design relies on (technical design, section 7.2) | M2, M4 |
| Q-04 | SQL parser choice (`sqlglot` versus `pglast`) on the attack cases | M4 |
| Q-05 | Current LangGraph API | M6 |
| Q-06 | Baseline accuracy, and whether targets SC-04, SC-05, and SC-10 need revision | M5 |
| Q-07 | AWS free-plan terms, eligible instance types, and storage and IPv4 charges | M11 |
| Q-08 | Streamlit sufficiency for the four components | M9 |
| Q-09 | HTTPS approach for the public demo | M11 |
| Q-10 | Feasibility of a second, free-tier model | M10 |

## 17. Future work

Seller-scoped mode with row-level security, additional playbooks (seller scorecard, payment mix), review-text themes through a sandboxed summariser, monitoring and alerting, a Next.js front end, larger datasets, and fine-tuning.

## Document history

| Version | Date | Change |
|---|---|---|
| 1.0 | 2026-10-15 | Initial version. |
| 1.1 | 2026-10-15 | Corrected the undelivered-order count (2,965 without a delivery date, not 2,963). Execution accuracy scored on answerable items with confidence intervals; out-of-scope items scored as routing only. Added non-thinking-mode requirement (verified provider default). Marked dataset figures provisional until reproduced. |
| 1.2 | 2026-10-15 | M1 reproduction of section 5 figures with our own SQL (see `docs/data_profile.md`): all match except the small-seller figure, which is 51 under the date-based definition of late (57 was the timestamp-based count). Reviews created before the delivery date: 5.3% ("about 5%" confirmed). |
