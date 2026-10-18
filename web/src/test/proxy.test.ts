// The proxy is the frontend's security boundary toward FastAPI: only allow-listed endpoints,
// the session token only from the httpOnly cookie, never back to the browser, and every POST
// only from this app's own pages.
// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import { COOKIE, forward, sameOrigin, sessionToken, signIn, signOut, signUp } from "@/lib/server/proxy";
import { allowed, parseEnv } from "@/lib/server/upstream";

const APP = "http://localhost:3000";
const TOKEN = "test-session-token-not-real";
const UUID = "44164307-2a09-4598-b9b0-270d432c7b0c";

afterEach(() => vi.restoreAllMocks());

function okFetch(body: unknown = { ok: true }, init: ResponseInit = { status: 200 }) {
  return vi.fn<typeof fetch>(async () => new Response(JSON.stringify(body), init));
}

function req(path: string, init: RequestInit & { cookie?: string; origin?: string | null } = {}) {
  const headers = new Headers(init.headers);
  if (init.cookie) headers.set("cookie", init.cookie);
  const origin = init.origin === undefined ? APP : init.origin;
  if (origin) headers.set("origin", origin);
  return new Request(`${APP}${path}`, { ...init, headers });
}

describe("allow-list", () => {
  it("parses .env lines with comments and quotes", () => {
    expect(parseEnv("A=1\n# x\n\nB='two'\nC=\"3\"\nbad line\n")).toEqual({ A: "1", B: "two", C: "3" });
  });

  it("allows only the listed endpoints and methods", () => {
    for (const [m, p] of [
      ["POST", "v1/ask"],
      ["GET", "v1/budget"],
      ["GET", "v1/catalog"],
      ["GET", `v1/requests/${UUID}`],
      ["GET", "v1/sessions"],
      ["GET", "v1/sessions/abc_123"],
      ["POST", "v1/sessions/abc_123/scope/clear"],
      ["GET", "v1/auth/me"],
      ["GET", `v1/auth/invites/${"a".repeat(43)}`],
      ["GET", "v1/admin/users"],
      ["POST", `v1/admin/users/${UUID}/disable`],
      ["POST", "v1/admin/invites"],
      ["POST", `v1/admin/invites/${UUID}/revoke`],
    ]) {
      expect(allowed(m, p)).toBe(true);
    }
    for (const [m, p] of [
      ["GET", "v1/ask"],
      ["GET", "v1/requests/../../etc"],
      ["POST", "v1/sessions"],
      ["GET", "docs"],
      ["POST", "v1/auth/login"], // only through the sign-in route, which sets the cookie
      ["POST", "v1/auth/signup"],
      ["POST", `v1/admin/users/${UUID}/delete`],
      ["GET", "v1/auth/invites/short"],
    ]) {
      expect(allowed(m, p)).toBe(false);
    }
  });
});

describe("forward", () => {
  it("rejects endpoints outside the allow-list without calling the API", async () => {
    const f = okFetch();
    const r = await forward(req("/api/docs"), ["docs"], f);
    expect(r.status).toBe(404);
    expect(f).not.toHaveBeenCalled();
  });

  it("sends the cookie's session as a Bearer token and no browser header", async () => {
    const f = okFetch({ request_id: "r1" });
    const request = req("/api/v1/ask", {
      method: "POST",
      cookie: `other=1; ${COOKIE}=${TOKEN}`,
      headers: { authorization: "Bearer forged", "x-access-code": "guess", "content-type": "application/json" },
      body: JSON.stringify({ question: "q", session_id: "s" }),
    });
    const r = await forward(request, ["v1", "ask"], f);
    expect(r.status).toBe(200);
    const [url, init] = f.mock.calls[0];
    expect(url).toBe("http://127.0.0.1:8000/v1/ask");
    expect(init?.headers).toEqual({ authorization: `Bearer ${TOKEN}`, "content-type": "application/json" });
  });

  it("sends no Authorization header when there is no session", async () => {
    const f = okFetch();
    await forward(req("/api/v1/health"), ["v1", "health"], f);
    expect(f.mock.calls[0][1]?.headers).toEqual({});
  });

  it("refuses a POST from another website (CSRF) or without an origin", async () => {
    for (const origin of ["https://evil.example", null]) {
      const f = okFetch();
      const r = await forward(req("/api/v1/ask", { method: "POST", origin, cookie: `${COOKIE}=${TOKEN}`, body: "{}" }), ["v1", "ask"], f);
      expect(r.status).toBe(403);
      expect(f).not.toHaveBeenCalled();
    }
    expect(sameOrigin(req("/x", { method: "POST" }))).toBe(true);
  });

  it("clears the cookie when the API no longer accepts the session", async () => {
    const f = okFetch({ error: { code: "unauthorized", message: "Please sign in again." } }, { status: 401 });
    const r = await forward(req("/api/v1/sessions", { cookie: `${COOKIE}=${TOKEN}` }), ["v1", "sessions"], f);
    expect(r.status).toBe(401);
    expect(r.headers.get("set-cookie")).toMatch(new RegExp(`^${COOKIE}=; .*Max-Age=0`));
  });

  it("passes API errors and Retry-After through, refuses big bodies and non-JSON replies", async () => {
    let f = okFetch({ error: { code: "rate_limited", message: "wait" } }, { status: 429, headers: { "retry-after": "7" } });
    let r = await forward(req("/api/v1/ask", { method: "POST", body: "{}" }), ["v1", "ask"], f);
    expect(r.status).toBe(429);
    expect(r.headers.get("retry-after")).toBe("7");

    f = okFetch();
    r = await forward(req("/api/v1/ask", { method: "POST", body: JSON.stringify({ question: "x".repeat(5000) }) }), ["v1", "ask"], f);
    expect(r.status).toBe(413);
    expect(f).not.toHaveBeenCalled();

    const html = vi.fn<typeof fetch>(async () => new Response("<html>Traceback…</html>", { status: 500 }));
    r = await forward(req("/api/v1/health"), ["v1", "health"], html);
    expect(r.status).toBe(502);
    expect(await r.text()).not.toContain("Traceback");
  });

  it("maps an unreachable API and a timeout to structured errors", async () => {
    const down = vi.fn<typeof fetch>(async () => {
      throw new TypeError("fetch failed");
    });
    let r = await forward(req("/api/v1/health"), ["v1", "health"], down);
    expect((await r.json()).error.code).toBe("connection_error");
    const slow = vi.fn<typeof fetch>(async () => {
      throw new DOMException("timed out", "TimeoutError");
    });
    r = await forward(req("/api/v1/health"), ["v1", "health"], slow);
    expect(r.status).toBe(504);
  });
});

describe("sign in, sign up, sign out", () => {
  const user = { id: "u1", email: "a@example.test", name: "A", role: "user" };

  it("keeps the token in an httpOnly cookie and never returns it to the browser", async () => {
    const f = okFetch({ token: TOKEN, user });
    const r = await signIn(req("/api/auth/login", { method: "POST", body: JSON.stringify({ email: "a@example.test", password: "pw" }) }), f);
    expect(r.status).toBe(200);
    const text = await r.text();
    expect(JSON.parse(text)).toEqual({ user });
    expect(text).not.toContain(TOKEN);
    const cookie = r.headers.get("set-cookie") ?? "";
    expect(cookie).toContain(`${COOKIE}=${TOKEN}`);
    expect(cookie).toContain("HttpOnly");
    expect(cookie).toContain("SameSite=Lax");
    expect(cookie).not.toContain("Secure"); // plain http on localhost; Secure on https
    const [url, init] = f.mock.calls[0];
    expect(url).toBe("http://127.0.0.1:8000/v1/auth/login");
    expect(init?.headers).toEqual({ "content-type": "application/json" });
  });

  it("marks the cookie Secure on https", async () => {
    const f = okFetch({ token: TOKEN, user });
    const request = new Request("https://app.example/api/auth/login", {
      method: "POST",
      headers: { origin: "https://app.example" },
      body: "{}",
    });
    const r = await signIn(request, f);
    expect(r.headers.get("set-cookie")).toContain("; Secure");
  });

  it("passes a failed sign-in through without setting a cookie", async () => {
    const f = okFetch({ error: { code: "invalid_credentials", message: "Email or password is wrong." } }, { status: 401 });
    const r = await signIn(req("/api/auth/login", { method: "POST", body: "{}" }), f);
    expect(r.status).toBe(401);
    expect(r.headers.get("set-cookie")).toBeNull();
    expect((await r.json()).error.code).toBe("invalid_credentials");
  });

  it("signs up through the API and starts a session the same way", async () => {
    const f = okFetch({ token: TOKEN, user });
    const r = await signUp(req("/api/auth/signup", { method: "POST", body: JSON.stringify({ invite: "x", name: "A", password: "p" }) }), f);
    expect(f.mock.calls[0][0]).toBe("http://127.0.0.1:8000/v1/auth/signup");
    expect(r.headers.get("set-cookie")).toContain(`${COOKIE}=${TOKEN}`);
    expect(await r.text()).not.toContain(TOKEN);
  });

  it("refuses sign-in from another website", async () => {
    const f = okFetch({ token: TOKEN, user });
    const r = await signIn(req("/api/auth/login", { method: "POST", origin: "https://evil.example", body: "{}" }), f);
    expect(r.status).toBe(403);
    expect(f).not.toHaveBeenCalled();
  });

  it("signs out at the API and clears the cookie", async () => {
    const f = okFetch({ ok: true });
    const r = await signOut(req("/api/auth/logout", { method: "POST", cookie: `${COOKIE}=${TOKEN}` }), f);
    expect(f.mock.calls[0][0]).toBe("http://127.0.0.1:8000/v1/auth/logout");
    expect(f.mock.calls[0][1]?.headers).toEqual({ authorization: `Bearer ${TOKEN}` });
    expect(r.headers.get("set-cookie")).toMatch(new RegExp(`^${COOKIE}=; .*Max-Age=0`));
  });

  it("reads the session from the cookie header only", () => {
    expect(sessionToken(req("/x", { cookie: `a=1; ${COOKIE}=abc%3D` }))).toBe("abc=");
    expect(sessionToken(req("/x", { headers: { authorization: "Bearer xyz" } }))).toBeNull();
  });
});
