"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  chartMeasures,
  compact,
  formatCell,
  formatMonth,
  humanize,
  isPartialRow,
  isRate,
  tableRecords,
} from "@/lib/format";
import { usePartialMonths } from "../catalog-context";

const COLORS = ["#4f46e5", "#0ea5e9", "#10b981", "#f59e0b", "#ef4444"];
const PARTIAL = "#a1a1aa";

/**
 * A chart over the result rows. Monthly points are joined with straight lines (a smoothed
 * curve invents values between months); three or fewer points are drawn as bars; one kind of
 * measure per chart; months the data only partly covers are drawn hollow (lines) or faded
 * (bars), with a note.
 */
export function ResultChart({
  kind,
  x,
  y,
  columns,
  rows,
}: {
  kind: "line" | "bar";
  x: string;
  y: string[];
  columns: string[];
  rows: unknown[][];
}) {
  const partialMonths = usePartialMonths();
  const data: Record<string, unknown>[] = tableRecords(columns, rows).map((r) => ({
    ...r,
    __partial: isPartialRow(r, x, partialMonths),
  }));
  const measures = chartMeasures(y);
  const shape = kind === "line" && data.length > 3 ? "line" : "bar";
  const anyPartial = data.some((d) => d.__partial);
  const isTime = x === "month" || /date|month|week|day/.test(x);
  const xFmt = (v: unknown) => (isTime ? formatMonth(v) : String(v));
  // Long identifiers (seller ids are 32 hex characters) are shortened on the axis only.
  const tickFmt = (v: unknown) => {
    const t = xFmt(v);
    return t.length > 14 ? `${t.slice(0, 6)}…${t.slice(-4)}` : t;
  };
  const yFmt = (v: number) => (measures.every(isRate) ? `${v}%` : compact(v));
  const tooltip = (
    <Tooltip
      cursor={{ fill: "rgba(99,102,241,0.06)" }}
      contentStyle={{ borderRadius: 8, border: "1px solid #e4e4e7", fontSize: 12, boxShadow: "0 4px 12px rgba(0,0,0,0.06)" }}
      labelFormatter={(v) => xFmt(v) + (data.find((d) => d[x] === v)?.__partial ? " (partial month)" : "")}
      formatter={(v, name) => [formatCell(String(name), v), humanize(String(name))]}
    />
  );
  const axes = (
    <>
      <CartesianGrid stroke="#f4f4f5" vertical={false} />
      <XAxis
        dataKey={x}
        tickFormatter={tickFmt}
        tick={{ fontSize: 11, fill: "#71717a" }}
        tickLine={false}
        axisLine={{ stroke: "#e4e4e7" }}
        interval="preserveStartEnd"
        minTickGap={16}
      />
      <YAxis tickFormatter={yFmt} tick={{ fontSize: 11, fill: "#71717a" }} tickLine={false} axisLine={false} width={52} />
    </>
  );
  return (
    <div>
      <div className="h-72 w-full" role="img" aria-label={`${shape} chart of ${measures.map(humanize).join(", ")} by ${humanize(x)}`}>
        <ResponsiveContainer width="100%" height="100%">
          {shape === "line" ? (
            <LineChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
              {axes}
              {tooltip}
              {measures.map((col, i) => {
                const color = COLORS[i % COLORS.length];
                return (
                  <Line
                    key={col}
                    type="linear"
                    dataKey={col}
                    stroke={color}
                    strokeWidth={2.25}
                    isAnimationActive={false}
                    dot={(props: { cx?: number; cy?: number; index?: number }) => {
                      const partial = data[props.index ?? 0]?.__partial;
                      return (
                        <circle
                          key={`${col}-${props.index}`}
                          cx={props.cx}
                          cy={props.cy}
                          r={partial ? 3.5 : 2.5}
                          fill={partial ? "#fff" : color}
                          stroke={partial ? PARTIAL : color}
                          strokeWidth={partial ? 1.5 : 0}
                        />
                      );
                    }}
                    activeDot={{ r: 5 }}
                  />
                );
              })}
            </LineChart>
          ) : (
            <BarChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
              {axes}
              {tooltip}
              {measures.map((col, i) => (
                <Bar key={col} dataKey={col} radius={[4, 4, 0, 0]} maxBarSize={56} isAnimationActive={false}>
                  {data.map((d, j) => (
                    <Cell key={j} fill={d.__partial ? PARTIAL : COLORS[i % COLORS.length]} fillOpacity={d.__partial ? 0.55 : 1} />
                  ))}
                </Bar>
              ))}
            </BarChart>
          )}
        </ResponsiveContainer>
      </div>
      {anyPartial && (
        <p className="mt-1 px-1 text-[11px] text-zinc-500">
          {shape === "line" ? "Hollow points" : "Grey bars"} are partial months: the data covers them only partly, so their values are not comparable.
        </p>
      )}
    </div>
  );
}
