"use client";

import clsx from "clsx";
import { Activity, Target } from "lucide-react";
import { GROUP_FIELDS, label, reportMetrics, stageRows, type Metric } from "@/lib/format";
import type { Findings, GroupRow } from "@/lib/types";
import { Badge, SectionTitle } from "../ui";

const VERDICT_TONE: Record<string, "bad" | "warn" | "good" | "neutral"> = {
  elevated: "bad",
  slightly_elevated: "warn",
  normal: "good",
  insufficient_data: "neutral",
};

export function MetricTile({ m }: { m: Metric }) {
  return (
    <div className="rounded-lg border border-zinc-200 bg-white px-4 py-3">
      <div className="text-xs font-medium text-zinc-500">{m.label}</div>
      <div className="mt-1 text-2xl font-semibold tracking-tight text-zinc-900 tabular-nums">{m.value}</div>
      {m.delta && (
        <div
          className={clsx(
            "mt-0.5 text-xs font-medium",
            m.worse === true ? "text-rose-600" : m.worse === false ? "text-emerald-600" : "text-zinc-500",
          )}
        >
          {m.delta}
        </div>
      )}
    </div>
  );
}

function StageComparison({ f }: { f: Findings }) {
  const rows = stageRows(f);
  if (!rows.length) return null;
  const max = Math.max(...rows.flatMap((r) => [r.period, r.baseline ?? 0]));
  return (
    <div>
      <SectionTitle
        aside={
          <span className="flex items-center gap-3 text-[11px] text-zinc-500">
            <span className="flex items-center gap-1"><i className="size-2 rounded-sm bg-brand-600" /> This period</span>
            <span className="flex items-center gap-1"><i className="size-2 rounded-sm bg-zinc-300" /> Baseline</span>
          </span>
        }
      >
        Where the days went
      </SectionTitle>
      <div className="space-y-3 rounded-lg border border-zinc-200 p-4">
        {rows.map((r) => {
          const diff = r.baseline != null ? r.period - r.baseline : null;
          return (
            <div key={r.stage} className="grid grid-cols-[120px_1fr_88px] items-center gap-3 text-sm">
              <span className="text-zinc-700">{r.stage}</span>
              <div className="space-y-1">
                <div className="h-2.5 rounded-full bg-brand-600" style={{ width: `${(r.period / max) * 100}%` }} />
                {r.baseline != null && (
                  <div className="h-2.5 rounded-full bg-zinc-300" style={{ width: `${(r.baseline / max) * 100}%` }} />
                )}
              </div>
              <span className="text-right tabular-nums">
                <span className="font-medium text-zinc-900">{r.period} d</span>
                {diff != null && (
                  <span className={clsx("block text-xs", diff > 0.5 ? "text-rose-600" : "text-zinc-500")}>
                    {diff >= 0 ? "+" : ""}
                    {diff.toFixed(2)} vs {r.baseline}
                  </span>
                )}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function GroupTable({ title, rows }: { title: string; rows: GroupRow[] }) {
  const hasExcess = rows.some((r) => r.excess_late_orders != null);
  const max = Math.max(...rows.map((r) => Math.max(r.rate ?? 0, r.baseline_rate ?? 0)), 1);
  return (
    <div>
      <SectionTitle>{title}</SectionTitle>
      <div className="overflow-hidden rounded-lg border border-zinc-200">
        <table className="w-full text-sm">
          <thead className="bg-zinc-50 text-xs text-zinc-600">
            <tr>
              <th className="px-3 py-2 text-left font-semibold">Name</th>
              <th className="px-3 py-2 text-right font-semibold">Orders</th>
              <th className="w-1/2 px-3 py-2 text-left font-semibold">Late rate vs baseline</th>
              {hasExcess && <th className="px-3 py-2 text-right font-semibold">Excess</th>}
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-100">
            {rows.map((r) => (
              <tr key={r.name}>
                <td className={clsx("px-3 py-2 whitespace-nowrap text-zinc-800", r.name.length > 20 && "font-mono text-xs")} title={r.name}>
                  {r.name.length > 20 ? `${r.name.slice(0, 10)}…${r.name.slice(-4)}` : label(r.name)}
                </td>
                <td className="px-3 py-2 text-right text-zinc-600 tabular-nums">{r.n?.toLocaleString("en-US")}</td>
                <td className="px-3 py-2">
                  <div className="flex items-center gap-2">
                    <div className="relative h-2 flex-1 rounded-full bg-zinc-100">
                      <div className="absolute inset-y-0 left-0 rounded-full bg-rose-400" style={{ width: `${(r.rate / max) * 100}%` }} />
                      <div className="absolute inset-y-[-3px] w-0.5 bg-zinc-500" style={{ left: `${(r.baseline_rate / max) * 100}%` }} title={`Baseline ${r.baseline_rate}%`} />
                    </div>
                    <span className="w-28 shrink-0 text-right text-xs text-zinc-600 tabular-nums">
                      <b className="font-semibold text-zinc-900">{r.rate}%</b> / {r.baseline_rate}%
                    </span>
                  </div>
                </td>
                {hasExcess && (
                  <td className="px-3 py-2 text-right font-medium text-zinc-900 tabular-nums">{r.excess_late_orders ?? "—"}</td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function InvestigationReport({
  verdict,
  topDriver,
  findings,
}: {
  verdict: string;
  topDriver: string;
  findings: Findings;
}) {
  const metrics = reportMetrics(findings);
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={VERDICT_TONE[verdict] ?? "neutral"} icon={<Activity className="size-3" />}>
          Verdict: {label(verdict)}
        </Badge>
        {topDriver && (
          <Badge tone="brand" icon={<Target className="size-3" />}>
            Top driver: {label(topDriver)}
          </Badge>
        )}
        {typeof findings.systemic === "boolean" && (
          <Badge>{findings.systemic ? "Systemic (widespread)" : "Concentrated"}</Badge>
        )}
        {typeof findings.period === "string" && <Badge>Period {findings.period}</Badge>}
      </div>
      {metrics.length > 0 && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
          {metrics.map((m) => (
            <MetricTile key={m.label} m={m} />
          ))}
        </div>
      )}
      <StageComparison f={findings} />
      <div className="space-y-5">
        {GROUP_FIELDS.map(([key, title]) =>
          Array.isArray(findings[key]) && (findings[key] as GroupRow[]).length ? (
            <GroupTable key={key} title={title} rows={findings[key] as GroupRow[]} />
          ) : null,
        )}
      </div>
    </div>
  );
}
