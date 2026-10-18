// A stand-in for the FastAPI service that replays recorded answers, so the frontend can be
// developed and demoed with no database and no model calls ($0).
//
//   node scripts/mock-api.mjs            # listens on 127.0.0.1:8100
//   API_URL=http://127.0.0.1:8100 npm run dev
//
// The access code for the mock is "mock" (it is not the real ACCESS_CODE).
// Answers come from src/test/fixtures/*.json, which are real responses stored in the trace
// database; the question picks one by keyword.
import { readFileSync, readdirSync } from "node:fs";
import { createServer } from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const dir = path.join(here, "..", "src", "test", "fixtures");
const fixtures = Object.fromEntries(
  readdirSync(dir)
    .filter((f) => f.endsWith(".json"))
    .map((f) => [f.replace(/\.json$/, ""), JSON.parse(readFileSync(path.join(dir, f), "utf8"))]),
);
const PORT = Number(process.env.MOCK_PORT ?? 8100);
// Conversation history, in memory: session id -> turns (lost when the mock stops).
const sessions = new Map();
const CODE = "mock";

const RULES = [
  [/dataset|schema|what can i ask|show me the data\b/i, "about"],
  [/\b(?:2019|202\d|2015)\b/i, "out_of_range"],
  [/2016/i, "partial_month"],
  [/why|investigat|so bad|what happened/i, "investigation"],
  [/trend|over time|monthly/i, "late_trend"],
  [/categor/i, "top_categories"],
  [/seller.*(most|top)|top.*seller/i, "top_sellers"],
  [/seller/i, "seller_lookup"],
  [/late/i, "late_count"],
  [/weather|stock|password|ignore/i, "refused"],
];

function pick(question) {
  for (const [re, name] of RULES) if (re.test(question) && fixtures[name]) return fixtures[name];
  return fixtures.clarify;
}
// catalog.json is the guide's data, not an answer: never picked for a question.

const send = (res, status, body) => {
  res.writeHead(status, { "content-type": "application/json" });
  res.end(JSON.stringify(body));
};

createServer((req, res) => {
  const url = new URL(req.url, "http://x");
  if (url.pathname === "/v1/health") return send(res, 200, { status: "ok", database: "ok", llm_enabled: true });
  if (req.headers["x-access-code"] !== CODE) {
    return send(res, 401, { error: { code: "unauthorized", message: "A valid access code is required." } });
  }
  if (url.pathname === "/v1/budget") {
    return send(res, 200, {
      total_usd: 0.0789, today_usd: 0, total_cap_usd: 1.9, daily_cap_usd: 0.4,
      remaining_total_usd: 1.8211, remaining_today_usd: 0.4, llm_enabled: true,
    });
  }
  if (url.pathname === "/v1/ask" && req.method === "POST") {
    let body = "";
    req.on("data", (c) => (body += c));
    req.on("end", () => {
      const { question = "", session_id } = JSON.parse(body || "{}");
      const r = structuredClone(pick(question));
      r.request_id = crypto.randomUUID();
      if (session_id) {
        const turns = sessions.get(session_id) ?? [];
        turns.push({ request_id: r.request_id, created_at: new Date().toISOString(), question, status: r.status, response: r, error: null });
        sessions.set(session_id, turns);
      }
      setTimeout(() => send(res, 200, r), 900);
    });
    return;
  }
  if (/^\/v1\/sessions\/[^/]+\/scope\/clear$/.test(url.pathname)) return send(res, 200, { cleared: true });
  if (url.pathname === "/v1/catalog") return send(res, 200, fixtures.catalog);
  if (url.pathname === "/v1/sessions") {
    const list = [...sessions.entries()].map(([id, t]) => ({
      session_id: id, title: t[0].question, questions: t.length,
      started_at: t[0].created_at, updated_at: t.at(-1).created_at,
    }));
    list.sort((a, b) => b.updated_at.localeCompare(a.updated_at));
    return send(res, 200, { sessions: list });
  }
  const s = /^\/v1\/sessions\/([A-Za-z0-9_-]{1,64})$/.exec(url.pathname);
  if (s) {
    const turns = sessions.get(s[1]);
    if (!turns) return send(res, 404, { error: { code: "not_found", message: "No such conversation." } });
    return send(res, 200, { session_id: s[1], scope_active: true, turns });
  }
  const m = /^\/v1\/requests\/([0-9a-f-]{36})$/.exec(url.pathname);
  if (m) {
    const r = fixtures.investigation;
    return send(res, 200, {
      request_id: m[1], created_at: new Date().toISOString(), status: "ok", route: r.route,
      latency_ms: r.usage.latency_ms, billed_cost_usd: r.usage.cost_usd, error: null, response: r,
      steps: [
        { step_no: 1, kind: "llm", payload: { model: "deepseek-flash", status: "ok", tokens_in: 1800, tokens_out: 90, cost_usd: 0.0003 }, ms: 1400 },
        ...r.evidence.map((e, i) => ({ step_no: i + 2, kind: e.kind === "playbook_step" ? "playbook" : "sql", payload: { evidence_id: e.id, row_count: e.row_count, rules_checked: e.validator?.rules_checked ?? [] }, ms: e.ms })),
        { step_no: 99, kind: "grounding", payload: r.grounding, ms: null },
        { step_no: 100, kind: "lint", payload: { causal_terms: [], warnings: [] }, ms: null },
      ],
    });
  }
  send(res, 404, { error: { code: "not_found", message: "No such endpoint." } });
}).listen(PORT, "127.0.0.1", () => console.log(`mock API on http://127.0.0.1:${PORT} (access code: ${CODE})`));
