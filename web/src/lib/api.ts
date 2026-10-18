// Browser-side calls to this app's /api proxy. Errors come back as codes from
// ERROR_MESSAGES, never as thrown exceptions, so every caller handles them the same way.

import type { AppConfig, AskResponse, Budget, Catalog, Health, SessionDetail, SessionSummary, Trace } from "./types";

export type ApiResult<T> = { ok: true; data: T } | { ok: false; code: string; status: number };

export interface Api {
  config(): Promise<ApiResult<AppConfig>>;
  health(): Promise<ApiResult<Health>>;
  budget(code: string): Promise<ApiResult<Budget>>;
  ask(code: string, question: string, sessionId: string): Promise<ApiResult<AskResponse>>;
  trace(code: string, requestId: string): Promise<ApiResult<Trace>>;
  clearScope(code: string, sessionId: string): Promise<ApiResult<{ cleared: boolean }>>;
  sessions(code: string): Promise<ApiResult<{ sessions: SessionSummary[] }>>;
  session(code: string, sessionId: string): Promise<ApiResult<SessionDetail>>;
  catalog(code: string): Promise<ApiResult<Catalog>>;
}

async function call<T>(method: string, path: string, code: string, body?: unknown): Promise<ApiResult<T>> {
  let r: Response;
  try {
    r = await fetch(`/api/${path}`, {
      method,
      headers: {
        "x-access-code": code,
        ...(body !== undefined ? { "content-type": "application/json" } : {}),
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
      cache: "no-store",
    });
  } catch {
    return { ok: false, code: "connection_error", status: 0 };
  }
  let data: unknown;
  try {
    data = await r.json();
  } catch {
    return { ok: false, code: "internal_error", status: r.status };
  }
  if (!r.ok) {
    const code_ = (data as { error?: { code?: string } })?.error?.code ?? "internal_error";
    return { ok: false, code: code_, status: r.status };
  }
  return { ok: true, data: data as T };
}

export const httpApi: Api = {
  config: () => call("GET", "config", ""),
  health: () => call("GET", "v1/health", ""),
  budget: (code) => call("GET", "v1/budget", code),
  ask: (code, question, sessionId) => call("POST", "v1/ask", code, { question, session_id: sessionId }),
  trace: (code, id) => call("GET", `v1/requests/${encodeURIComponent(id)}`, code),
  clearScope: (code, sessionId) => call("POST", `v1/sessions/${encodeURIComponent(sessionId)}/scope/clear`, code),
  sessions: (code) => call("GET", "v1/sessions", code),
  session: (code, sessionId) => call("GET", `v1/sessions/${encodeURIComponent(sessionId)}`, code),
  catalog: (code) => call("GET", "v1/catalog", code),
};
