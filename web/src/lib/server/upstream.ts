// Server-only: how the Next.js server reaches the FastAPI backend.
//
// The browser never talks to FastAPI directly. It calls this app's /api/* routes, which
// forward a fixed allowlist of endpoints. That keeps API_URL off the client and needs no
// CORS on the API. The user's sign-in token lives in an httpOnly cookie that only this
// server reads (see proxy.ts); the browser's JavaScript never sees it.

import { existsSync, readFileSync } from "node:fs";
import path from "node:path";

/** The project's .env: next to pyproject.toml, which is web/'s parent (or the cwd itself
 * when the server is started from the project root as `next dev web`). */
function envFile(): string {
  if (process.env.ORDERINTEL_ENV_FILE) return process.env.ORDERINTEL_ENV_FILE;
  const root = [path.resolve(process.cwd(), ".."), process.cwd()].find((d) =>
    existsSync(/*turbopackIgnore: true*/ path.join(d, "pyproject.toml")),
  );
  return path.join(root ?? path.resolve(process.cwd(), ".."), ".env");
}

/** Parse KEY=VALUE lines (comments, blank lines and surrounding quotes handled). */
export function parseEnv(text: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || line.startsWith("#")) continue;
    const eq = line.indexOf("=");
    if (eq < 1) continue;
    const key = line.slice(0, eq).trim();
    let value = line.slice(eq + 1).trim();
    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
      value = value.slice(1, -1);
    }
    out[key] = value;
  }
  return out;
}

function projectEnv(): Record<string, string> {
  try {
    // Read at runtime only; the file is not part of the build. Only API_URL is used.
    return parseEnv(readFileSync(/*turbopackIgnore: true*/ envFile(), "utf8"));
  } catch {
    return {};
  }
}

export function apiUrl(): string {
  return (process.env.API_URL || projectEnv().API_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");
}

const UUID = "[0-9a-fA-F-]{36}";

/** The FastAPI endpoints the browser may reach through the proxy, as (method, pattern).
 * Sign-in, sign-up and sign-out have their own routes (they set or clear the cookie). */
export const ALLOWED: [string, RegExp][] = [
  ["GET", /^v1\/health$/],
  ["GET", /^v1\/budget$/],
  ["GET", /^v1\/catalog$/],
  ["POST", /^v1\/ask$/],
  ["GET", new RegExp(`^v1/requests/${UUID}$`)],
  ["GET", /^v1\/sessions$/],
  ["GET", /^v1\/sessions\/[A-Za-z0-9_-]{1,64}$/],
  ["POST", /^v1\/sessions\/[A-Za-z0-9_-]{1,64}\/scope\/clear$/],
  ["GET", /^v1\/auth\/me$/],
  ["GET", /^v1\/auth\/invites\/[A-Za-z0-9_-]{20,100}$/],
  ["GET", /^v1\/admin\/users$/],
  ["POST", new RegExp(`^v1/admin/users/${UUID}/(?:disable|enable)$`)],
  ["GET", /^v1\/admin\/invites$/],
  ["POST", /^v1\/admin\/invites$/],
  ["POST", new RegExp(`^v1/admin/invites/${UUID}/revoke$`)],
];

export function allowed(method: string, subpath: string): boolean {
  return ALLOWED.some(([m, re]) => m === method && re.test(subpath));
}
