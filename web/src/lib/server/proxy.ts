// Server-only: forward one allowed request to FastAPI and pass its JSON back unchanged.
// Only the access code and the JSON body are forwarded; no other client header is.

import { accessCodeFor, allowed, apiUrl } from "./upstream";

const MAX_BODY_BYTES = 4096; // a question is at most 500 characters
const TIMEOUT_MS = 120_000; // investigations run several queries

function error(status: number, code: string, message: string): Response {
  return Response.json({ error: { code, message } }, { status });
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
    body = await request.text();
    if (new TextEncoder().encode(body).length > MAX_BODY_BYTES) {
      return error(413, "invalid_request", "Request body too large.");
    }
  }

  const headers: Record<string, string> = {
    "x-access-code": accessCodeFor(request.headers.get("x-access-code")),
  };
  if (body !== undefined) headers["content-type"] = "application/json";

  let upstream: Response;
  try {
    upstream = await fetchImpl(`${apiUrl()}/${subpath}`, {
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

  const text = await upstream.text();
  try {
    JSON.parse(text);
  } catch {
    return error(502, "internal_error", "The API returned an unreadable response.");
  }
  const out = new Headers({ "content-type": "application/json", "cache-control": "no-store" });
  const retry = upstream.headers.get("retry-after");
  if (retry) out.set("retry-after", retry);
  return new Response(text, { status: upstream.status, headers: out });
}
