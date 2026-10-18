// Server-only: the bridge between the browser and FastAPI.
//
// * forward(): one allow-listed request, with the user's session token taken from the
//   httpOnly cookie and sent as "Authorization: Bearer". No browser header is forwarded.
// * authFlow() (signIn() / signUp()): sign-in, emailed-code and password-reset steps. The
//   session token, the challenge between password and code, and the trusted-device token
//   are kept in httpOnly cookies; the browser gets only the rest of the answer.
// * signOut(): end the session at the API and clear the cookie.
// * Every POST must come from this app's own pages (Origin check), so another website
//   cannot make a signed-in browser send requests here (cross-site request forgery).
// * Behind Caddy (TRUST_PROXY=1, set in the Docker deployment only), the visitor's address
//   from Caddy's X-Forwarded-For goes to the API, so sign-in and email limits count each
//   visitor separately instead of everyone as this server.

import { allowed, apiUrl } from "./upstream";

export const COOKIE = "oi_session";
export const CHALLENGE = "oi_challenge";
export const DEVICE = "oi_device";
const SESSION_SECONDS = 7 * 24 * 60 * 60; // the API's session lifetime
const CHALLENGE_SECONDS = 15 * 60; // a code lives 10 minutes; a resend extends it
const DEVICE_SECONDS = 30 * 24 * 60 * 60; // "trust this device for 30 days"
const AUTH_PATH = "/api/auth"; // the challenge and device cookies go only to sign-in routes
const MAX_BODY_BYTES = 4096; // a question is at most 500 characters
const TIMEOUT_MS = 120_000; // investigations run several queries

function error(status: number, code: string, message: string): Response {
  return Response.json({ error: { code, message } }, { status, headers: { "cache-control": "no-store" } });
}

function readCookie(request: Request, wanted: string): string | null {
  const header = request.headers.get("cookie") ?? "";
  for (const part of header.split(";")) {
    const [name, ...rest] = part.trim().split("=");
    if (name === wanted) {
      try {
        return decodeURIComponent(rest.join("=")) || null;
      } catch {
        return null;
      }
    }
  }
  return null;
}

/** The session token from the request's cookie header, if any. */
export function sessionToken(request: Request): string | null {
  return readCookie(request, COOKIE);
}

/** The address the browser used. Behind Caddy (TRUST_PROXY=1) this server is reached over
 * plain http inside Docker, so the browser's https address comes from Caddy's
 * X-Forwarded-Proto and X-Forwarded-Host (Caddy sets them and ignores any a visitor sends). */
export function publicOrigin(request: Request): string {
  const url = new URL(request.url);
  if (process.env.TRUST_PROXY !== "1") return url.origin;
  const proto = (request.headers.get("x-forwarded-proto") ?? "").split(",")[0].trim();
  const host = (request.headers.get("x-forwarded-host") ?? request.headers.get("host") ?? "").split(",")[0].trim();
  const scheme = proto === "https" || proto === "http" ? proto : url.protocol.replace(":", "");
  return /^[A-Za-z0-9.:[\]-]{1,255}$/.test(host) ? `${scheme}://${host}` : url.origin;
}

function cookie(request: Request, name: string, value: string, maxAge: number, path = "/"): string {
  const secure = publicOrigin(request).startsWith("https:") ? "; Secure" : "";
  return `${name}=${encodeURIComponent(value)}; Path=${path}; HttpOnly; SameSite=Lax; Max-Age=${maxAge}${secure}`;
}

/** POSTs must come from this app's own origin (cross-site request forgery protection). */
export function sameOrigin(request: Request): boolean {
  const origin = request.headers.get("origin");
  return origin !== null && origin === publicOrigin(request);
}

async function readBody(request: Request): Promise<string | Response> {
  const body = await request.text();
  if (new TextEncoder().encode(body).length > MAX_BODY_BYTES) {
    return error(413, "invalid_request", "Request body too large.");
  }
  return body;
}

/** The visitor's address as Caddy saw it; only when this server runs behind Caddy, because
 * anyone can send an X-Forwarded-For header to a server that is reached directly. */
export function clientAddress(request: Request): string | null {
  if (process.env.TRUST_PROXY !== "1") return null;
  const first = (request.headers.get("x-forwarded-for") ?? "").split(",")[0].trim();
  return /^[0-9a-fA-F.:]{2,45}$/.test(first) ? first : null;
}

async function callApi(
  method: string,
  subpath: string,
  token: string | null,
  body: string | undefined,
  fetchImpl: typeof fetch,
  client: string | null = null,
): Promise<Response> {
  const headers: Record<string, string> = {};
  if (token) headers.authorization = `Bearer ${token}`;
  if (body !== undefined) headers["content-type"] = "application/json";
  if (client) headers["x-forwarded-for"] = client;
  try {
    return await fetchImpl(`${apiUrl()}/${subpath}`, {
      method,
      headers,
      body: body || undefined,
      signal: AbortSignal.timeout(TIMEOUT_MS),
      cache: "no-store",
    });
  } catch (e) {
    const timedOut = e instanceof DOMException && e.name === "TimeoutError";
    return timedOut
      ? error(504, "timeout", "The API took too long to answer.")
      : error(502, "connection_error", "The API is not reachable.");
  }
}

async function jsonOf(upstream: Response): Promise<unknown | Response> {
  const text = await upstream.text();
  try {
    return JSON.parse(text);
  } catch {
    return error(502, "internal_error", "The API returned an unreadable response.");
  }
}

export async function forward(
  request: Request,
  segments: string[],
  fetchImpl: typeof fetch = fetch,
): Promise<Response> {
  const subpath = segments.join("/");
  const method = request.method.toUpperCase();
  if (!allowed(method, subpath)) return error(404, "not_found", "No such endpoint.");

  let body: string | undefined;
  if (method === "POST") {
    if (!sameOrigin(request)) return error(403, "forbidden", "Requests must come from this app.");
    const read = await readBody(request);
    if (read instanceof Response) return read;
    body = read;
  }

  const upstream = await callApi(method, subpath, sessionToken(request), body, fetchImpl, clientAddress(request));
  const data = await jsonOf(upstream);
  if (data instanceof Response) return data;
  const out = new Headers({ "content-type": "application/json", "cache-control": "no-store" });
  const retry = upstream.headers.get("retry-after");
  if (retry) out.set("retry-after", retry);
  // A session the API no longer accepts is removed from the browser too.
  if (upstream.status === 401 && sessionToken(request)) out.append("set-cookie", cookie(request, COOKIE, "", 0));
  return new Response(JSON.stringify(data), { status: upstream.status, headers: out });
}

/** Sign-in, sign-up and password-reset steps: the API path, and the cookie the step needs.
 * The challenge (between the password and the emailed code) and the trusted-device token
 * live in httpOnly cookies like the session, so page scripts never see them either. */
export const AUTH_ACTIONS: Record<string, { path: string; needs?: "challenge" | "device" }> = {
  login: { path: "v1/auth/login", needs: "device" },
  signup: { path: "v1/auth/signup" },
  verify: { path: "v1/auth/login/verify", needs: "challenge" },
  resend: { path: "v1/auth/login/resend", needs: "challenge" },
  forgot: { path: "v1/auth/password/forgot" },
  "forgot-resend": { path: "v1/auth/password/resend", needs: "challenge" },
  reset: { path: "v1/auth/password/reset", needs: "challenge" },
};

/** One step: forward the JSON body (plus the cookie the step needs), then turn any token,
 * device token or challenge in the answer into cookies and return the rest. */
export async function authFlow(request: Request, action: string, fetchImpl: typeof fetch = fetch): Promise<Response> {
  const step = Object.hasOwn(AUTH_ACTIONS, action) ? AUTH_ACTIONS[action] : undefined;
  if (!step) return error(404, "not_found", "No such endpoint.");
  if (!sameOrigin(request)) return error(403, "forbidden", "Requests must come from this app.");
  const read = await readBody(request);
  if (read instanceof Response) return read;
  let body: Record<string, unknown>;
  try {
    const parsed: unknown = JSON.parse(read || "{}");
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("not an object");
    body = parsed as Record<string, unknown>;
  } catch {
    return error(400, "invalid_request", "The request body must be a JSON object.");
  }
  // Only this server sets these, from its own cookies.
  delete body.challenge;
  delete body.device;
  if (step.needs === "challenge") {
    const challenge = readCookie(request, CHALLENGE);
    if (!challenge) return error(400, "code_expired", "This code has expired. Please start again.");
    body.challenge = challenge;
  }
  if (step.needs === "device") {
    const device = readCookie(request, DEVICE);
    if (device) body.device = device;
  }

  const upstream = await callApi("POST", step.path, null, JSON.stringify(body), fetchImpl, clientAddress(request));
  const data = await jsonOf(upstream);
  if (data instanceof Response) return data;
  const out = new Headers({ "content-type": "application/json", "cache-control": "no-store" });
  if (!upstream.ok) {
    const retry = upstream.headers.get("retry-after");
    if (retry) out.set("retry-after", retry);
    return new Response(JSON.stringify(data), { status: upstream.status, headers: out });
  }
  const { token, device_token, challenge, ...rest } = data as Record<string, unknown>;
  if ((action === "login" || action === "signup" || action === "verify") && !token && !rest.code_required) {
    return error(502, "internal_error", "The API returned no session.");
  }
  if (typeof challenge === "string") out.append("set-cookie", cookie(request, CHALLENGE, challenge, CHALLENGE_SECONDS, AUTH_PATH));
  if (typeof token === "string") out.append("set-cookie", cookie(request, COOKIE, token, SESSION_SECONDS));
  if (typeof token === "string" || action === "reset") out.append("set-cookie", cookie(request, CHALLENGE, "", 0, AUTH_PATH));
  if (typeof device_token === "string") out.append("set-cookie", cookie(request, DEVICE, device_token, DEVICE_SECONDS, AUTH_PATH));
  return new Response(JSON.stringify(rest), { status: 200, headers: out });
}

export function signIn(request: Request, fetchImpl: typeof fetch = fetch): Promise<Response> {
  return authFlow(request, "login", fetchImpl);
}

export function signUp(request: Request, fetchImpl: typeof fetch = fetch): Promise<Response> {
  return authFlow(request, "signup", fetchImpl);
}

export async function signOut(request: Request, fetchImpl: typeof fetch = fetch): Promise<Response> {
  if (!sameOrigin(request)) return error(403, "forbidden", "Requests must come from this app.");
  const token = sessionToken(request);
  if (token) await callApi("POST", "v1/auth/logout", token, undefined, fetchImpl, clientAddress(request));
  const out = new Headers({ "content-type": "application/json", "cache-control": "no-store" });
  out.append("set-cookie", cookie(request, COOKIE, "", 0));
  return new Response(JSON.stringify({ ok: true }), { status: 200, headers: out });
}
