# Provider facts (Q-02)

**Primary provider: DeepSeek** (paid, US$2 budget). **Second provider: Gemini API free tier** (comparison only, F-16; calibrated 2026-10-16, second half of this file).

## DeepSeek (primary)

- Models `deepseek-flash` (primary) and `deepseek-v4-pro` (comparison); prices and peak hours as in PRD section 13 (official pricing page, 2026-10-15).
- Thinking is on by default at `high` effort. It is disabled on every call with `extra_body={"thinking": {"type": "disabled"}}`; thinking mode ignores `temperature`; chain-of-thought appears in `reasoning_content` (official thinking-mode guide, 2026-10-16).
- Top-up completed by the owner on 2026-10-16. Budget cap in code stays at US$1.90 (owner's decision).

### DeepSeek calibration run (2026-10-16 10:38 UTC, Friday, off-peak; `scripts/calibrate.py --provider deepseek`, 10 calls, owner-approved)

All calls `temperature=0`, `max_tokens=2048`, thinking disabled except the control call. Raw results: git-ignored `eval/cache/calibration_deepseek.json`.

| Call | Result | Latency | Cache miss / hit / output tokens | Reasoning tokens | Cost (off-peak) |
|---|---|---|---|---|---|
| latency_1 | OK | 1.45 s | 18 / 0 / 5 | none | $0.000006 |
| latency_2 | OK | 0.67 s | 18 / 0 / 5 | none | $0.000006 |
| latency_3 | OK | 0.84 s | 18 / 0 / 5 | none | $0.000006 |
| thinking_default_control (no `thinking` parameter) | OK | 0.99 s | 44 / 0 / 26 | **20** (`reasoning_content` returned) | $0.000022 |
| json_object | OK, valid JSON | 0.74 s | 44 / 0 / 16 | none | $0.000016 |
| sqlgen_canceled | OK | 1.00 s | 1,853 / 0 / 68 | none | $0.000319 |
| sqlgen_late_rate | OK | 1.26 s | 196 / **1,664** / 135 | none | $0.000115 |
| sqlgen_canceled_repeat_cache | OK | 1.17 s | 189 / **1,664** / 71 | none | $0.000076 |
| sqlgen_monthly | OK | 1.32 s | 195 / **1,664** / 113 | none | $0.000102 |
| comparison_model (`deepseek-v4-pro`) | OK | 2.45 s | 18 / 0 / 5 | none | $0.000022 |
| **Total** | **10 of 10** | | | | **$0.000689** (at peak prices it would be $0.001379) |

### Findings (Q-02 answered for DeepSeek)

1. **Usage field names:** `prompt_cache_hit_tokens`, `prompt_cache_miss_tokens`, `completion_tokens`, and `completion_tokens_details.reasoning_tokens` (also `prompt_tokens_details.cached_tokens`). The usage ledger records all of them.
2. **Thinking is really off** with `extra_body={"thinking": {"type": "disabled"}}`: no reasoning tokens and no `reasoning_content`. Without the parameter, even a trivial prompt produced 20 reasoning tokens, and the prompt grew from 18 to 44 tokens.
3. **Prompt caching works automatically and across different questions:** after the first SQL call, 1,664 of about 1,860 prompt tokens were cache hits (the static prefix: rules, view documentation, glossary). A cached SQL call costs about $0.0001 instead of $0.0003, roughly three times cheaper, which validates the "static prefix first" prompt layout (technical design 10.3).
4. **Latency:** 0.7-1.5 s for `deepseek-flash`, 2.45 s for `deepseek-v4-pro` on a tiny prompt.
5. **JSON output** (`response_format: json_object`) returned valid JSON in every call.
6. **Cost estimate check (A-03):** the PRD estimated about $0.001 per ablation question; measured is $0.0001-0.0003 off-peak, well within the estimate.

### First signal on SQL quality (development questions only)

| Golden item | Result |
|---|---|
| agg_10 canceled orders (twice) | Correct both times: 625 |
| trend_01 orders per month in 2017 | Correct: 12 rows, in order, matching the reference |
| agg_04 overall late-delivery rate | 6.79%, scored correct within tolerance; the reference is 6.77%. Like Gemini, the model restricted the data to the analysis window on its own and said so in its assumptions. |

Both providers read the glossary's "analysis window" as applying to an "overall" figure. This is a glossary ambiguity to settle before M5 (see `docs/progress.md`).

### Not yet verified

- Rate limits and balance expiry (not observable in 10 calls; check the DeepSeek console).
- That the console balance change matches the computed cost ($0.0007 may display as $0.00).

## Gemini API free tier (second provider)

Recorded for M0b. Sources: Google's official documentation (models, pricing, thinking, OpenAI compatibility, Google AI plans pages, retrieved 2026-10-15), the owner's Google AI Studio rate-limit page (2026-10-16), and our own test calls.

## Account and project

- Key created in Google AI Studio, project "AI INTELLIGENCE AGENT", shown as **Free tier**; billing is **not** set up. Over-quota requests are therefore refused (HTTP 429), not charged.
- The owner's Google AI Pro subscription does not apply to API keys: its benefits "apply only within the Google AI Studio web interface" (Google AI plans page). Its Cloud credits would require enabling billing, so they are not used.
- The key is stored only in `.env` (git-ignored) and is never printed.

## Free-tier limits (AI Studio, 2026-10-16)

| Model | RPM | Input TPM | RPD | Our caps (`.env`) |
|---|---|---|---|---|
| `gemini-3.5-flash-lite` (primary) | 15 | 250,000 | 500 | 12 RPM, 200,000 TPM, 450 RPD |
| `gemini-3.8-flash` (comparison) | to record | to record | to record | — |

Daily limits reset at midnight Pacific time (08:00 UTC; 13:30 in India). Limits apply per project, not per key.

Planning consequence: the whole project needs about 1,400 requests (PRD section 13), i.e. at least four days at 450 per day; a 120-call ablation batch takes at least 10 minutes at 12 RPM.

## Endpoint and behaviour (official documentation)

- OpenAI-compatible base URL `https://generativelanguage.googleapis.com/v1beta/openai/` (beta), used with the `openai` Python SDK.
- Thinking is on by default and cannot be switched off on Gemini 3 models; `reasoning_effort` or `extra_body.google.thinking_config` (not both) lowers it. Thinking tokens are output tokens and count toward each call's output limit.
- Paid-tier prices, used only for the notional cost report: `gemini-3.5-flash-lite` $0.30 input / $2.50 output per 1M tokens; `gemini-3.8-flash` $0.75 / $3.75 through 2026-12-31.
- Free-tier content may be used to improve Google's products (acceptable under PRD NFR-05).

## Test call 1 (2026-10-16)

| Item | Result |
|---|---|
| Model | `gemini-3.5-flash-lite` (returned as the same ID) |
| Parameters | `temperature=0`, `max_tokens=512`, `reasoning_effort="low"` (accepted) |
| Prompt | Asked for an exact JSON object |
| Answer | `{"ok": true}`, `finish_reason=stop` |
| Usage | 15 prompt, 5 completion, 20 total tokens; no thinking-token count reported (`completion_tokens_details` is null) |
| Latency | 11.4 s |
| Cost | $0 (1 of 500 daily requests) |

## Gemini calibration run (2026-10-16, `scripts/calibrate.py --provider gemini`, 10 calls, owner-approved)

All calls: `temperature=0`, `max_tokens=2048`, spaced 6 s apart. Raw results are in the git-ignored `eval/cache/calibration_gemini.json`.

| Call | Settings | Result | Latency | Prompt / completion / total tokens |
|---|---|---|---|---|
| latency_1 | tiny prompt, `reasoning_effort=low` | OK | 1.45 s | 15 / 5 / 20 |
| latency_2 | same | OK | 1.90 s | 15 / 5 / 20 |
| latency_3 | same | OK | 1.20 s | 15 / 5 / 20 |
| thinking_minimal | `reasoning_effort=minimal` | OK (accepted) | 1.08 s | 15 / 5 / 20 |
| thinking_none | `reasoning_effort=none` | **HTTP 400** invalid argument | 0.46 s | — |
| thinking_visible | `thinking_level=low`, `include_thoughts=true` via `extra_body` | OK; no thought text returned | 1.09 s | 15 / 5 / 20 |
| json_schema | `response_format` JSON schema | OK, schema-conforming JSON | 1.45 s | 11 / 13 / 24 |
| sqlgen_low | realistic SQL prompt (views + glossary), `low`, JSON object | OK, valid SQL | 1.21 s | 1,981 / 58 / 2,039 |
| sqlgen_medium | same prompt size, `medium` | OK, valid SQL | 4.50 s | 1,988 / 169 / **3,185** |
| comparison_model | `gemini-3.8-flash`, tiny prompt | **HTTP 503** "high demand", not retried | 1.71 s | — |

### Findings

1. **Latency:** warm calls take 1.1-1.9 s; the first test call (11.4 s) was a cold start. A realistic SQL-generation call at `low` took 1.2 s, so NFR-03 (p95 ≤ 20 s for three calls) looks achievable.
2. **Thinking cannot be disabled** (`none` is rejected with HTTP 400); `minimal` and `low` are accepted.
3. **Thinking tokens are hidden but measurable:** the endpoint reports no thinking field, but `total_tokens` includes them. Thinking tokens = total − prompt − completion: 0 at `low` (2,039 = 1,981 + 58), **1,028 at `medium`** (3,185 − 1,988 − 169), which also added about 3.3 s. The usage ledger will record thinking tokens with this formula.
4. **Default thinking level for the client: `low`.** It produced correct SQL with no measurable thinking overhead; `medium` is kept as an option to test in M5 if accuracy needs it.
5. **Structured JSON works** both with a JSON schema and with `json_object`.
6. **Prompt size:** the generated view documentation plus glossary is about 1,980 tokens, far below the 250,000 input TPM.
7. **Free-tier capacity can fail transiently:** `gemini-3.8-flash` returned 503 "high demand". The client must retry 503 as well as 429 (bounded, with backoff), and evaluation runs must resume from the cache.
8. **Notional cost** at paid-tier prices of a realistic SQL call (`low`): 1,981 × $0.30/1M + 58 × $2.50/1M ≈ **$0.0007**.

### First signal on SQL quality (development questions only)

| Golden item | Model SQL | Result |
|---|---|---|
| agg_10 "How many orders were canceled?" | `SELECT count(*) ... WHERE order_status = 'canceled'` | Validated, executed: 625, matches the reference |
| agg_04 "overall late-delivery rate" | late rate over delivered orders, but **filtered to the analysis window** (2017-01 to 2018-08) | Validated, executed: 6.79%; reference (all data) 6.77%; **scored correct only because 0.02 points is inside the rounding tolerance** |

Two issues for M5, recorded rather than fixed here:
- The glossary does not say whether the analysis window applies to totals and "overall" figures; the model applied it, the references do not. The glossary should state when the window applies.
- The comparer's absolute tolerance (0.051) cannot distinguish display rounding from a small scope difference on percentages. Known limitation; mismatched scopes will be tagged manually in M5 review.

### Still open

- `gemini-3.8-flash` free-tier limits (toggle "All models" on the AI Studio rate-limit page) and one successful call; retry later.

### Usage so far

11 requests to `gemini-3.5-flash-lite`-class models in total (1 test + 10 calibration), about 7,500 tokens, **$0.00 billed**.
