// Server-only: how the Next.js server reaches the FastAPI backend.
//
// The browser never talks to FastAPI directly. It calls this app's /api/* routes, which
// forward a fixed allowlist of endpoints. That keeps API_URL off the client, needs no CORS
// on the API, and lets local mode supply the access code without it reaching the browser.
//
// Local mode (`npm run dev:local`, sets ORDERINTEL_LOCAL=1): the server reads ACCESS_CODE
// from the project's .env and sends it itself. Accepted only when API_URL points to
// localhost or 127.0.0.1, so a deployed frontend always asks the user for the code.
// The value is kept in this process; it is never logged or returned.

import { existsSync, readFileSync } from "node:fs";
import path from "node:path";

const LOCAL_HOSTS = new Set(["localhost", "127.0.0.1", "[::1]"]);

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
    // Read at runtime only; the file is not part of the build.
    return parseEnv(readFileSync(/*turbopackIgnore: true*/ envFile(), "utf8"));
  } catch {
    return {};
  }
}

export function apiUrl(): string {
  return (process.env.API_URL || projectEnv().API_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");
}

export function isLocalHost(url: string): boolean {
  try {
    return LOCAL_HOSTS.has(new URL(url).hostname);
  } catch {
    return false;
  }
}

/** True when local mode is requested AND the API is on this machine. */
export function localMode(): boolean {
  return process.env.ORDERINTEL_LOCAL === "1" && isLocalHost(apiUrl());
}

/** The access code to forward: the server's own in local mode, else the user's. */
export function accessCodeFor(userCode: string | null): string {
  if (localMode()) return projectEnv().ACCESS_CODE ?? "";
  return userCode ?? "";
}

/** The FastAPI endpoints the frontend may reach, as (method, path pattern). */
export const ALLOWED: [string, RegExp][] = [
  ["GET", /^v1\/health$/],
  ["GET", /^v1\/budget$/],
  ["GET", /^v1\/catalog$/],
  ["POST", /^v1\/ask$/],
  ["GET", /^v1\/requests\/[0-9a-fA-F-]{36}$/],
  ["GET", /^v1\/sessions$/],
  ["GET", /^v1\/sessions\/[A-Za-z0-9_-]{1,64}$/],
  ["POST", /^v1\/sessions\/[A-Za-z0-9_-]{1,64}\/scope\/clear$/],
];

export function allowed(method: string, subpath: string): boolean {
  return ALLOWED.some(([m, re]) => m === method && re.test(subpath));
}
