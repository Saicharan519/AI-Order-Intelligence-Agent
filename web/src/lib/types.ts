// The API response contract, mirrored from src/orderintel/api/schemas.py.

export type Route = "answer" | "investigate" | "clarify" | "refuse" | "about";
export type Status = "ok" | "clarify" | "refused" | "sql_failed" | "not_available" | "error";

export interface Scope {
  period: { start: string; end: string; source: "sql" | "default" | "none" } | null;
  population: string | null;
  filters: string[];
  definitions: string[];
  assumptions: string[];
  n: number;
  truncated: boolean;
  partial_period_warnings: string[];
}

export interface Evidence {
  id: string;
  kind: "sql" | "playbook_step";
  sql: string | null;
  params: Record<string, unknown>;
  row_count: number;
  rows_preview: unknown[][];
  validator: { ok: boolean; rules_checked: string[] } | null;
  attempts: { stage?: string; sql?: string; feedback?: string }[];
  ms: number;
}

export interface Usage {
  llm_calls: number;
  cached_calls: number;
  tokens_in: number;
  tokens_cache_hit: number;
  tokens_out: number;
  cost_usd: number;
  latency_ms: number;
}

export interface Followup {
  label: string;
  question: string;
  inherits_scope: boolean;
}

export interface GroupRow {
  name: string;
  n: number;
  rate: number;
  baseline_rate: number;
  excess_late_orders?: number | null;
  [key: string]: unknown;
}

export type Findings = Record<string, unknown> & {
  late_rate?: number | null;
  one_star_share?: number | null;
};

export type Component =
  | { type: "text"; variant: "answer_card"; columns: string[]; row: unknown[] }
  | { type: "text"; variant?: string; text: string }
  | { type: "table"; columns: string[]; rows: unknown[][] }
  | { type: "chart"; kind: "line" | "bar"; x: string; y: string[] }
  | { type: "report"; verdict: string; top_driver: string; playbook: string; findings: Findings }
  | {
      type: "about";
      dataset: Catalog["dataset"];
      facts: Catalog["facts"];
      views: { name: string; description: string }[];
      examples: Catalog["examples"];
      limits: string[];
    };

export interface AskResponse {
  request_id: string;
  route: Route;
  status: Status;
  headline: string;
  components: Component[];
  scope: Scope;
  evidence: Evidence[];
  notes: string[];
  caveats: string[];
  warnings: string[];
  grounding: { numbers_checked: number; untraced: string[]; causal_terms: string[]; regenerated: boolean };
  followups: Followup[];
  usage: Usage;
}

export interface Budget {
  total_usd: number;
  today_usd: number;
  total_cap_usd: number;
  daily_cap_usd: number;
  remaining_total_usd: number;
  remaining_today_usd: number;
  llm_enabled: boolean;
}

export interface Health {
  status: string;
  database: "ok" | "unavailable";
  llm_enabled: boolean;
}

export interface TraceStep {
  step_no: number;
  kind: "llm" | "validator" | "sql" | "playbook" | "grounding" | "lint" | string;
  payload: Record<string, unknown>;
  ms: number | null;
}

export interface Trace {
  request_id: string;
  created_at: string;
  status: string;
  route: string | null;
  latency_ms: number | null;
  billed_cost_usd: number;
  error: string | null;
  steps: TraceStep[];
}

export interface SessionSummary {
  session_id: string;
  title: string;
  started_at: string;
  updated_at: string;
  questions: number;
}

export interface SessionTurn {
  request_id: string;
  created_at: string;
  question: string;
  status: string;
  response: AskResponse | null;
  error: string | null;
}

export interface SessionDetail {
  session_id: string;
  scope_active: boolean;
  turns: SessionTurn[];
}

export interface Catalog {
  dataset: { name: string; description: string; source: string };
  facts: {
    orders: number;
    delivered_orders: number;
    customers: number;
    customer_states: number;
    sellers: number;
    products: number;
    categories: number;
    first_month: string | null;
    last_month: string | null;
    analysis_window: { start: string; end: string } | null;
    partial_months: { month: string; orders: number }[];
    months: { month: string; orders: number; partial: boolean; in_window: boolean }[];
  };
  views: { name: string; description: string; columns: string[]; column_notes?: Record<string, string> }[];
  definitions: { term: string; definition: string }[];
  examples: { topic: string; questions: string[] }[];
  limits: string[];
  missing_fields: { field: string; closest: string }[];
}

export interface AppConfig {
  local: boolean;
}
