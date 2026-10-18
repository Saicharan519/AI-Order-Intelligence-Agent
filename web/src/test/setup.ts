import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";
import { router, setQuery } from "./navigation-mock";

// Pages use Next's router and URL query; tests get a recording stand-in.
vi.mock("next/navigation", async () => (await import("./navigation-mock")).navigation);

afterEach(() => {
  cleanup();
  router.replace.mockClear();
  router.push.mockClear();
  setQuery("");
});

// jsdom has no layout engine; recharts' ResponsiveContainer needs these.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver ??= ResizeObserverStub as unknown as typeof ResizeObserver;
if (typeof Element !== "undefined") Element.prototype.scrollIntoView ??= function () {};
