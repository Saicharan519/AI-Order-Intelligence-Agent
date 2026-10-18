// Server-only: the bridge between the browser and FastAPI.
//
// * forward(): one allow-listed request, with the user's session token taken from the
//   httpOnly cookie and sent as "Authorization: Bearer". No browser header is forwarded.
// * signIn() / signUp(): call the API, then keep the returned token in the cookie and
//   return only the user, never the token.
// * signOut(): end the session at the API and clear the cookie.
// * Every POST must come from this app's own pages (Origin check), so another website
//   cannot make a signed-in browser send requests here (cross-site request forgery).

import { allowed, apiUrl } from "./upstream";

export const COOKIE = "oi_session";
const SESSION_SECONDS = 7 * 24 * 60 * 60; // the API's session lifetime
const MAX_BODY_BYTES = 4096; // a question is at most 500 characters
const TIMEOUT_MS = 120_000; // investigations run several queries

function error(status: number, code: string, message: string): Response {
  return Response.json({ error: { code, message } }, { status, headers: { "cache-control": "no-store" } });
}

/** The session token from the request's cookie header, if any. */
export function sessionToken(request: Request): string | null {
  const header = request.headers.get("cookie") ?? "";
  for (const part of header.split(";")) {
    const [name, ...rest] = part.trim().split("=");
    if (name === COOKIE) return decodeURIComponent(rest.join("=")) || null;
  }
  return null;
}

function cookie(request: Request, token: string, maxAge: number): string {
  const secure = new URL(request.url).protocol === "https:" ? "; Secure" : "";
  return `${COOKIE}=${encodeURIComponent(token)}; Path=/; HttpOnly; SameSite=Lax; Max-Age=${maxAge}${secure}`;
}

/** POSTs must come from this app's own origin (cross-site request forgery protection). */
export function sameOrigin(request: Request): boolean {
  const origin = request.headers.get("origin");
  return origin !== null && origin === new URL(request.url).origin;
}

async function readBody(request: Request): Promise<string | Response> {
  const body = await request.text();
  if (new TextEncoder().encode(body).length > MAX_BODY_BYTES) {
    return error(413, "invalid_request", "Request body too large.");
  }
  return body;
}

async function callApi(
  method: string,
  subpath: string,
  token: string | null,
  body: string | undefined,
  fetchImpl: typeof fetch,
): Promise<Response> {
  const headers: Record<string, string> = {};
  if (token) headers.authorization = `Bearer ${token}`;
  if (body !== undefined) headers["content-type"] = "application/json";
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

  const upstream = await callApi(method, subpath, sessionToken(request), body, fetchImpl);
  const data = await jsonOf(upstream);
  if (data instanceof Response) return data;
  const out = new Headers({ "content-type": "application/json", "cache-control": "no-store" });
  const retry = upstream.headers.get("retry-after");
  if (retry) out.set("retry-after", retry);
  // A session the API no longer accepts is removed from the browser too.
  if (upstream.status === 401 && sessionToken(request)) out.append("set-cookie", cookie(request, "", 0));
  return new Response(JSON.stringify(data), { status: upstream.status, headers: out });
}

/** Sign in or sign up: the API returns {token, user}; the browser gets {user} and a cookie. */
async function startSession(
  request: Request,
  subpath: "v1/auth/login" | "v1/auth/signup",
  fetchImpl: typeof fetch,
): Promise<Response> {
  if (!sameOrigin(request)) return error(403, "forbidden", "Requests must come from this app.");
  const read = await readBody(request);
  if (read instanceof Response) return read;
  const upstream = await callApi("POST", subpath, null, read, fetchImpl);
  const data = await jsonOf(upstream);
  if (data instanceof Response) return data;
  const out = new Headers({ "content-type": "application/json", "cache-control": "no-store" });
  if (!upstream.ok) {
    const retry = upstream.headers.get("retry-after");
    if (retry) out.set("retry-after", retry);
    return new Response(JSON.stringify(data), { status: upstream.status, headers: out });
  }
  const { token, user } = data as { token?: string; user?: unknown };
  if (!token) return error(502, "internal_error", "The API returned no session.");
  out.append("set-cookie", cookie(request, token, SESSION_SECONDS));
  return new Response(JSON.stringify({ user }), { status: 200, headers: out });
}

export function signIn(request: Request, fetchImpl: typeof fetch = fetch): Promise<Response> {
  return startSession(request, "v1/auth/login", fetchImpl);
}

export function signUp(request: Request, fetchImpl: typeof fetch = fetch): Promise<Response> {
  return startSession(request, "v1/auth/signup", fetchImpl);
}

export async function signOut(request: Request, fetchImpl: typeof fetch = fetch): Promise<Response> {
  if (!sameOrigin(request)) return error(403, "forbidden", "Requests must come from this app.");
  const token = sessionToken(request);
  if (token) await callApi("POST", "v1/auth/logout", token, undefined, fetchImpl);
  const out = new Headers({ "content-type": "application/json", "cache-control": "no-store" });
  out.append("set-cookie", cookie(request, "", 0));
  return new Response(JSON.stringify({ ok: true }), { status: 200, headers: out });
}
