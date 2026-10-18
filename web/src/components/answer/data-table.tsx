"use client";

import clsx from "clsx";
import { ArrowDown, ArrowUp, Download } from "lucide-react";
import { useMemo, useState } from "react";
import { formatCell, formatMonth, humanize, plural, toCsv, toNumber } from "@/lib/format";
import { Button } from "../ui";

export function DataTable({
  columns,
  rows,
  filename = "results.csv",
  download = true,
}: {
  columns: string[];
  rows: unknown[][];
  filename?: string;
  download?: boolean;
}) {
  const [sort, setSort] = useState<{ col: number; dir: 1 | -1 } | null>(null);
  const data = useMemo(() => rows.map((r) => r.map(toNumber)), [rows]);
  const sorted = useMemo(() => {
    if (!sort) return data;
    return [...data].sort((a, b) => {
      const x = a[sort.col];
      const y = b[sort.col];
      if (typeof x === "number" && typeof y === "number") return (x - y) * sort.dir;
      return String(x ?? "").localeCompare(String(y ?? "")) * sort.dir;
    });
  }, [data, sort]);
  const numeric = columns.map((_, i) => data.some((r) => typeof r[i] === "number"));

  const save = () => {
    const blob = new Blob([toCsv(columns, rows)], { type: "text/csv;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  return (
    <div className="overflow-hidden rounded-lg border border-zinc-200">
      <div className="scroll-thin max-h-96 overflow-auto">
        <table className="w-full text-sm">
          <thead className="sticky top-0 z-10 bg-zinc-50">
            <tr>
              {columns.map((c, i) => (
                <th
                  key={c}
                  scope="col"
                  aria-sort={sort?.col === i ? (sort.dir === 1 ? "ascending" : "descending") : "none"}
                  className={clsx(
                    "border-b border-zinc-200 px-3 py-2 text-xs font-semibold whitespace-nowrap text-zinc-600",
                    numeric[i] ? "text-right" : "text-left",
                  )}
                >
                  <button
                    type="button"
                    className="inline-flex items-center gap-1 hover:text-zinc-900"
                    onClick={() =>
                      setSort((s) => (s?.col === i ? (s.dir === 1 ? { col: i, dir: -1 } : null) : { col: i, dir: 1 }))
                    }
                  >
                    {humanize(c)}
                    {sort?.col === i && (sort.dir === 1 ? <ArrowUp className="size-3" /> : <ArrowDown className="size-3" />)}
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-100">
            {sorted.map((r, ri) => (
              <tr key={ri} className="hover:bg-zinc-50/70">
                {r.map((v, ci) => (
                  <td
                    key={ci}
                    className={clsx(
                      "px-3 py-1.5 whitespace-nowrap text-zinc-800",
                      numeric[ci] ? "text-right tabular-nums" : "text-left",
                      typeof v === "string" && v.length >= 24 && "font-mono text-xs",
                    )}
                  >
                    {columns[ci] === "month" ? formatMonth(v) : formatCell(columns[ci], v)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {download && (
        <div className="flex items-center justify-between border-t border-zinc-200 bg-zinc-50/60 px-3 py-1.5 text-xs text-zinc-500">
          <span>{plural(rows.length, "row")}</span>
          <Button size="sm" variant="ghost" onClick={save}>
            <Download className="size-3.5" /> CSV
          </Button>
        </div>
      )}
    </div>
  );
}
