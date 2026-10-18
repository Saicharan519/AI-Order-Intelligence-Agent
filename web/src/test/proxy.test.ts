// The proxy is the frontend's security boundary toward FastAPI: only allowlisted endpoints,
// only the access code and JSON body forwarded, and the server's own code used only in
// local mode against a localhost API.
// @vitest-environment node
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { forward } from "@/lib/server/proxy";
import { accessCodeFor, allowed, localMode, parseEnv } from "@/lib/server/upstream";

const FAKE_CODE = "test-only-code-1234"; // a made-up value, not the project's ACCESS_CODE

function useEnvFile(text: string) {
  const dir = mkdtempSync(path.join(tmpdir(), "oi-web-"));
  const file = path.join(dir, ".env");
  writeFileSync(file, text);
  process.env.ORDERINTEL_ENV_FILE = file;
}

beforeEach(() => {
  delete process.env.ORDERINTEL_LOCAL;
  delete process.env.API_URL;
  useEnvFile(`# comment\nACCESS_CODE="${FAKE_CODE}"\nAPI_URL=http://127.0.0.1:8000\n`);
});

afterEach(() => {
  delete process.env.ORDERINTEL_ENV_FILE;
  vi.restoreAllMocks();
});

function okFetch(body: unknown = { ok: true }, init: ResponseInit = { status: 200 }) {
  return vi.fn<typeof fetch>(async () => new Response(JSON.stringify(body), init));
}

describe("upstream settings", () => {
  it("parses .env lines with comments and quotes", () => {
    expect(parseEnv("A=1\n# x\n\nB='two'\nC=\"3\"\nbad line\n")).toEqual({ A: "1", B: "two", C: "3" });
  });

  it("allows only the eight API endpoints", () => {
    expect(allowed("POST", "v1/ask")).toBe(true);
    expect(allowed("GET", "v1/ask")).toBe(false);
    expect(allowed("GET", "v1/budget")).toBe(true);
    expect(allowed("GET", "v1/requests/44164307-2a09-4598-b9b0-270d432c7b0c")).toBe(true);
    expect(allowed("GET", "v1/requests/../../etc")).toBe(false);
    expect(allowed("POST", "v1/sessions/abc_123/scope/clear")).toBe(true);
    expect(allowed("GET", "v1/sessions")).toBe(true);
    expect(allowed("GET", "v1/catalog")).toBe(true);
    expect(allowed("POST", "v1/catalog")).toBe(false);
    expect(allowed("GET", "v1/sessions/abc_123")).toBe(true);
    expect(allowed("POST", "v1/sessions")).toBe(false);
    expect(allowed("GET", "v1/sessions/a/b")).toBe(false);
    expect(allowed("GET", "docs")).toBe(false);
    expect(allowed("GET", "v1/health/../budget")).toBe(false);
  });

  it("uses the server's code only in local mode", () => {
    expect(localMode()).toBe(false);
    expect(accessCodeFor("typed")).toBe("typed");
    expect(accessCodeFor(null)).toBe("");
    process.env.ORDERINTEL_LOCAL = "1";
    expect(localMode()).toBe(true);
    expect(accessCodeFor("typed")).toBe(FAKE_CODE);
  });

  it("refuses local mode when the API is not on this machine", () => {
    process.env.ORDERINTEL_LOCAL = "1";
    process.env.API_URL = "https://api.example.com";
    expect(localMode()).toBe(false);
    expect(accessCodeFor("typed")).toBe("typed");
  });
});

describe("forward", () => {
  it("rejects endpoints outside the allowlist without calling the API", async () => {
    const f = okFetch();
    const r = await forward(new Request("http://x/api/docs"), ["docs"], f);
    expect(r.status).toBe(404);
    expect((await r.json()).error.code).toBe("not_found");
    expect(f).not.toHaveBeenCalled();
  });

  it("forwards only the access code and the JSON body", async () => {
    const f = okFetch({ request_id: "r1" });
    const req = new Request("http://x/api/v1/ask", {
      method: "POST",
      headers: { "x-access-code": "typed", cookie: "session=1", authorization: "Bearer t", "content-type": "application/json" },
      body: JSON.stringify({ question: "q", session_id: "s" }),
    });
    const r = await forward(req, ["v1", "ask"], f);
    expect(r.status).toBe(200);
    const [url, init] = f.mock.calls[0];
    expect(url).toBe("http://127.0.0.1:8000/v1/ask");
    expect(init?.headers).toEqual({ "x-access-code": "typed", "content-type": "application/json" });
    expect(init?.body).toBe(JSON.stringify({ question: "q", session_id: "s" }));
  });

  it("never returns the server's code to the browser in local mode", async () => {
    process.env.ORDERINTEL_LOCAL = "1";
    const f = okFetch({ total_usd: 0 });
    const r = await forward(new Request("http://x/api/v1/budget"), ["v1", "budget"], f);
    expect(f.mock.calls[0][1]?.headers).toEqual({ "x-access-code": FAKE_CODE });
    const text = await r.text();
    expect(text).not.toContain(FAKE_CODE);
    expect([...r.headers.values()].join(" ")).not.toContain(FAKE_CODE);
  });

  it("passes API errors and Retry-After through", async () => {
    const f = okFetch({ error: { code: "rate_limited", message: "wait" } }, { status: 429, headers: { "retry-after": "7" } });
    const r = await forward(new Request("http://x/api/v1/ask", { method: "POST", body: "{}" }), ["v1", "ask"], f);
    expect(r.status).toBe(429);
    expect(r.headers.get("retry-after")).toBe("7");
    expect((await r.json()).error.code).toBe("rate_limited");
  });

  it("refuses oversized bodies", async () => {
    const f = okFetch();
    const big = JSON.stringify({ question: "x".repeat(5000) });
    const r = await forward(new Request("http://x/api/v1/ask", { method: "POST", body: big }), ["v1", "ask"], f);
    expect(r.status).toBe(413);
    expect(f).not.toHaveBeenCalled();
  });

  it("maps an unreachable API and a timeout to structured errors", async () => {
    const down = vi.fn(async () => {
      throw new TypeError("fetch failed");
    });
    let r = await forward(new Request("http://x/api/v1/health"), ["v1", "health"], down);
    expect(r.status).toBe(502);
    expect((await r.json()).error.code).toBe("connection_error");

    const slow = vi.fn(async () => {
      throw new DOMException("timed out", "TimeoutError");
    });
    r = await forward(new Request("http://x/api/v1/health"), ["v1", "health"], slow);
    expect(r.status).toBe(504);
    expect((await r.json()).error.code).toBe("timeout");
  });

  it("refuses a non-JSON reply instead of passing it on", async () => {
    const f = vi.fn(async () => new Response("<html>Traceback…</html>", { status: 500 }));
    const r = await forward(new Request("http://x/api/v1/health"), ["v1", "health"], f);
    expect(r.status).toBe(502);
    expect(await r.text()).not.toContain("Traceback");
  });
});
