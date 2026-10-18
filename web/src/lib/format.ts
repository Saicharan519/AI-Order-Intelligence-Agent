// Pure presentation helpers (no React), ported from src/orderintel/ui/view.py so the
// two frontends say the same things. Unit tested in src/test/format.test.ts.

import type { Findings, Scope, Usage } from "./types";

// Every error code the API (or the proxy) can return, in words for the user.
export const ERROR_MESSAGES: Record<string, string> = {
  budget_exhausted:
    "The spending limit for the language model is reached, so no question can be answered right now. No call was made.",
  llm_disabled: "Questions are paused by the operator (kill switch).",
  rate_limited: "Too many questions in a short time. Please wait a moment and try again.",
  unauthorized: "Please sign in.",
  invalid_credentials: "Email or password is wrong.",
  too_many_attempts: "Too many failed attempts. Please wait 15 minutes and try again.",
  user_budget_exhausted: "You have used today's question budget. It resets at midnight UTC.",
  invalid_invite: "This invite link is not valid: it may be used or expired. Ask the admin for a new one.",
  weak_password: "Choose a stronger password: at least 10 characters.",
  email_taken: "An account with this email already exists.",
  forbidden: "Only an admin can do that.",
  invalid_email: "Enter a valid email address.",
  invalid_name: "Enter your name (up to 80 characters).",
  access_not_configured: "The server has no access code configured, so it refuses all questions.",
  provider_error: "The language model service is unavailable. Please try again later.",
  invalid_request: "The question could not be sent: keep it between 1 and 500 characters.",
  internal_error: "Something went wrong on the server.",
  not_found: "That request was not found.",
  connection_error: "The API is not reachable. Is it running on the configured API_URL?",
  timeout: "The API took too long to answer. Please try again.",
  not_finished: "This question did not finish (the API stopped before answering), so no answer was saved.",
};

export function errorMessage(code: string | null | undefined): string {
  return ERROR_MESSAGES[code ?? ""] ?? ERROR_MESSAGES.internal_error;
}

// Statuses that are answers but not successes: (tone, message).
export const STATUS_MESSAGES: Record<string, ["info" | "error", string]> = {
  clarify: ["info", "The question is ambiguous. Please choose or rephrase."],
  refused: ["info", "This question is outside what the data can answer."],
  sql_failed: [
    "error",
    "No safe query could be produced for this question (the validator rejected every attempt, or the query failed or timed out). Nothing was run against the data.",
  ],
  not_available: ["info", "The data has nothing for that period or analysis."],
  error: ["error", "The request failed."],
};

/** The scope statement (FR-08) as labelled lines. */
export function scopeLines(scope: Scope): { label: string; text: string }[] {
  const out: { label: string; text: string }[] = [];
  if (scope.period) out.push({ label: "Period", text: `${scope.period.start} to ${scope.period.end}` });
  if (scope.population) out.push({ label: "Population", text: scope.population });
  for (const f of scope.filters ?? []) out.push({ label: "Filter", text: f });
  for (const d of scope.definitions ?? []) out.push({ label: "Definition", text: d });
  for (const a of scope.assumptions ?? []) out.push({ label: "Assumption", text: a });
  if (scope.n) {
    out.push({
      label: "Rows",
      text: scope.n.toLocaleString("en-US") + (scope.truncated ? " (truncated at 500)" : ""),
    });
  }
  return out;
}

/** Short chips for the session scope bar: period and population only. */
export function scopeChips(scope: Scope): string[] {
  return scopeLines(scope)
    .filter((l) => l.label === "Period" || l.label === "Population")
    .map((l) => `${l.label}: ${l.text}`);
}

/** API rows carry decimals as strings; turn numeric strings back into numbers. */
export function toNumber(v: unknown): unknown {
  if (typeof v === "string" && v.trim() !== "" && /^-?\d+(\.\d+)?$/.test(v.trim())) {
    return Number(v);
  }
  return v;
}

export function tableRecords(columns: string[], rows: unknown[][]): Record<string, unknown>[] {
  return rows.map((r) => Object.fromEntries(columns.map((c, i) => [c, toNumber(r[i])])));
}

/** "late_rate_pct" -> "Late rate %", "seller_id" -> "Seller ID". */
export function humanize(column: string): string {
  const words = column
    .replace(/_pct$/, "_%")
    .split("_")
    .filter(Boolean)
    .map((w) => (w === "id" ? "ID" : w));
  const text = words.join(" ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

const MONEY_RE = /(revenue|price|value|freight|payment|gmv|amount|aov|sales)/i;
const RATE_RE = /(_pct|_rate|rate_|share|percent)/i;

export function isMoney(column: string): boolean {
  return MONEY_RE.test(column) && !RATE_RE.test(column);
}

export function isRate(column: string): boolean {
  return RATE_RE.test(column);
}

/** One kind of measure per chart: rates, else money, else counts (mirrors the API's rule, and
 * also fixes answers saved before it, which can mix revenue and counts on one axis). */
export function chartMeasures(y: string[]): string[] {
  const rates = y.filter(isRate);
  if (rates.length) return rates;
  const money = y.filter(isMoney);
  return money.length ? money : y;
}

/** True for a row the data only partly covers: its own flag, or a month in the catalog's list. */
export function isPartialRow(row: Record<string, unknown>, x: string, partialMonths: Set<string>): boolean {
  if (row.is_partial === true || row.partial_month === true) return true;
  const v = row[x];
  return typeof v === "string" && partialMonths.has(v.slice(0, 7));
}

/** Display a cell value: money as R$, rates with %, integers with separators. */
export function formatCell(column: string, value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value !== "number") return String(value);
  if (isMoney(column)) {
    return "R$" + value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  if (isRate(column)) return `${value.toLocaleString("en-US", { maximumFractionDigits: 2 })}%`;
  return value.toLocaleString("en-US", { maximumFractionDigits: 2 });
}

/** Compact axis labels: 497970 -> "498K". */
export function compact(value: number): string {
  return new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(value);
}

/** "2017-03-01" -> "Mar 2017"; other strings unchanged. */
export function formatMonth(v: unknown): string {
  if (typeof v !== "string") return String(v);
  const m = /^(\d{4})-(\d{2})(-01)?$/.exec(v);
  if (!m) return v;
  const names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return `${names[Number(m[2]) - 1]} ${m[1]}`;
}

export function usageParts(u: Usage): string[] {
  const calls = `${u.llm_calls ?? 0} model call${u.llm_calls === 1 ? "" : "s"}` +
    (u.cached_calls ? ` (${u.cached_calls} cached)` : "");
  return [
    calls,
    `${(u.tokens_in ?? 0).toLocaleString("en-US")} in / ${(u.tokens_out ?? 0).toLocaleString("en-US")} out tokens`,
    `$${(u.cost_usd ?? 0).toFixed(5)}`,
    `${((u.latency_ms ?? 0) / 1000).toFixed(1)} s`,
  ];
}

export interface Metric {
  label: string;
  value: string;
  delta: string | null;
  // Up is bad for late rate and one-star share, so the delta is coloured by `worse`.
  worse: boolean | null;
}

/** Headline numbers of either playbook. */
export function reportMetrics(f: Findings): Metric[] {
  const out: Metric[] = [];
  const num = (k: string) => (typeof f[k] === "number" ? (f[k] as number) : null);
  const signed = (d: number) => `${d >= 0 ? "+" : ""}${d}`;
  if (f.late_rate != null) {
    const d = num("delta_points") ?? 0;
    out.push({ label: "Late rate", value: `${f.late_rate}%`, delta: `${signed(d)} pts vs ${num("baseline_rate")}% baseline`, worse: d > 0 });
    out.push({ label: "Late orders", value: (num("late_orders") ?? 0).toLocaleString("en-US"), delta: null, worse: null });
    out.push({ label: "Delivered orders", value: (num("delivered_orders") ?? 0).toLocaleString("en-US"), delta: null, worse: null });
  }
  if (f.one_star_share != null) {
    const d = num("delta_points") ?? 0;
    out.push({ label: "1-star share", value: `${f.one_star_share}%`, delta: `${signed(d)} pts vs ${num("one_star_share_baseline")}% baseline`, worse: d > 0 });
    out.push({ label: "Average score", value: String(num("avg_score")), delta: `baseline ${num("avg_score_baseline")}`, worse: null });
  }
  return out;
}

export interface StageRow {
  stage: string;
  period: number;
  baseline: number | null;
}

export function stageRows(f: Findings): StageRow[] {
  const rows: StageRow[] = [];
  for (const [stage, key] of [
    ["Seller handling", "handling_days"],
    ["Carrier transit", "transit_days"],
    ["Promised", "promised_days"],
  ] as const) {
    if (typeof f[key] === "number") {
      const b = f[`${key}_baseline`];
      rows.push({ stage, period: f[key] as number, baseline: typeof b === "number" ? b : null });
    }
  }
  return rows;
}

export const GROUP_FIELDS: [string, string][] = [
  ["top_states", "States by excess late orders"],
  ["top_sellers", "Sellers by excess late orders"],
  ["top_categories", "Categories with the highest late rate"],
  ["worst_categories", "Categories with the lowest scores"],
  ["worst_sellers", "Sellers with the lowest scores"],
];

/** "carrier_transit" -> "Carrier transit". */
export function label(s: string | null | undefined): string {
  if (!s) return "";
  const t = s.replace(/_/g, " ");
  return t.charAt(0).toUpperCase() + t.slice(1);
}

/** RFC 4180 CSV for the table download. */
export function toCsv(columns: string[], rows: unknown[][]): string {
  const cell = (v: unknown) => {
    const s = v === null || v === undefined ? "" : String(v);
    return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return [columns, ...rows].map((r) => r.map(cell).join(",")).join("\r\n");
}

/** "1 row", "2,000 rows". */
export function plural(n: number, word: string, many = `${word}s`): string {
  return `${n.toLocaleString("en-US")} ${n === 1 ? word : many}`;
}

/** A session id matching the API's pattern ^[A-Za-z0-9_-]{1,64}$. */
export function newSessionId(): string {
  return crypto.randomUUID().replace(/-/g, "").slice(0, 16);
}
