// Orders per month across the whole data: shows at a glance why the data "starts in 2016"
// but trends "use 2017 to 2018". Bars inside the analysis window are coloured; the sparse
// months before and after it are grey. Figures come from the catalog (GET /v1/catalog).
"use client";

import clsx from "clsx";
import { formatMonth, plural } from "@/lib/format";
import type { Catalog } from "@/lib/types";

export function DataTimeline({ facts }: { facts: Catalog["facts"] }) {
  const months = facts.months ?? [];
  if (!months.length) return null;
  const max = Math.max(...months.map((m) => m.orders), 1);
  const w = facts.analysis_window;
  return (
    <figure aria-label="Orders per month across the data" className="rounded-lg border border-zinc-200 p-4">
      <div className="flex h-24 items-end gap-[3px]">
        {months.map((m) => (
          <div
            key={m.month}
            title={`${formatMonth(m.month)} · ${plural(m.orders, "order")}${m.partial ? " (partial month)" : ""}`}
            className="group relative flex h-full flex-1 items-end"
          >
            <div
              className={clsx(
                "w-full rounded-t-sm transition-opacity group-hover:opacity-80",
                m.in_window ? "bg-brand-500" : "bg-zinc-300",
              )}
              style={{ height: `${Math.max((m.orders / max) * 100, m.orders ? 2 : 0.5)}%` }}
            />
          </div>
        ))}
      </div>
      <div className="mt-1 flex gap-[3px] text-[10px] text-zinc-500">
        {months.map((m, i) => (
          <span key={m.month} className="flex-1 text-center">
            {i === 0 || m.month.endsWith("-01") ? m.month.slice(0, 4) : ""}
          </span>
        ))}
      </div>
      <figcaption className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-zinc-600">
        <span className="flex items-center gap-1.5">
          <i className="size-2.5 rounded-sm bg-brand-500" /> Steady months{w ? `: ${formatMonth(w.start)} to ${formatMonth(w.end)}` : ""} (trends use these)
        </span>
        <span className="flex items-center gap-1.5">
          <i className="size-2.5 rounded-sm bg-zinc-300" /> Sparse months at the edges of the data
        </span>
      </figcaption>
    </figure>
  );
}
