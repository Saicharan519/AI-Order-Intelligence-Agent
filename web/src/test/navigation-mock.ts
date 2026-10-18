// A stand-in for next/navigation in tests: records redirects and serves a settable URL query.
import { vi } from "vitest";

export const router = { replace: vi.fn(), push: vi.fn(), refresh: vi.fn(), back: vi.fn() };
let query = "";

export function setQuery(q: string) {
  query = q;
}

export const navigation = {
  useRouter: () => router,
  useSearchParams: () => new URLSearchParams(query),
  usePathname: () => "/",
};
