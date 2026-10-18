"use client";

import clsx from "clsx";
import { Bot, Database, Loader2, ShieldCheck, Sigma, SpellCheck, Workflow, X } from "lucide-react";
import { useEffect, useState } from "react";
import type { Api } from "@/lib/api";
import { errorMessage, plural } from "@/lib/format";
import type { Trace, TraceStep } from "@/lib/types";
import { Badge, Callout } from "./ui";

const STEP_META: Record<string, { icon: typeof Bot; title: string }> = {
  llm: { icon: Bot, title: "Model call" },
  validator: { icon: ShieldCheck, title: "SQL validator" },
  sql: { icon: Database, title: "Query executed" },
  playbook: { icon: Workflow, title: "Playbook step" },
  grounding: { icon: Sigma, title: "Number grounding" },
  lint: { icon: SpellCheck, title: "Causal-language lint" },
};

function summary(s: TraceStep): string {
  const p = s.payload as Record<string, unknown>;
  switch (s.kind) {
    case "llm":
      return `${p.model} · ${p.status} · ${Number(p.tokens_in ?? 0).toLocaleString("en-US")} in / ${Number(p.tokens_out ?? 0).toLocaleString("en-US")} out · $${Number(p.cost_usd ?? 0).toFixed(5)}`;
    case "validator":
      return `${p.evidence_id} attempt ${p.attempt}: ${p.stage}${p.feedback ? ` (${p.feedback})` : ""}`;
    case "sql":
    case "playbook":
      return `${p.evidence_id} · ${plural(Number(p.row_count ?? 0), "row")} · ${plural((p.rules_checked as string[] | undefined)?.length ?? 0, "rule")} checked`;
    case "grounding":
      return `${plural(Number(p.numbers_checked ?? 0), "number")} checked · ${(p.untraced as string[] | undefined)?.length ?? 0} untraced${p.regenerated ? " · regenerated" : ""}`;
    case "lint":
      return (p.causal_terms as string[] | undefined)?.length ? `flagged: ${(p.causal_terms as string[]).join(", ")}` : "no causal claims";
    default:
      return "";
  }
}

export function TraceDrawer({
  api,
  requestId,
  onClose,
}: {
  api: Api;
  requestId: string | null;
  onClose: () => void;
}) {
  const [trace, setTrace] = useState<Trace | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!requestId) return;
    let live = true; // the drawer is keyed by request id, so state starts empty
    api.trace(requestId).then((r) => {
      if (!live) return;
      if (r.ok) setTrace(r.data);
      else setError(errorMessage(r.code));
    });
    return () => {
      live = false;
    };
  }, [api, requestId]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  if (!requestId) return null;
  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <button type="button" aria-label="Close trace" className="absolute inset-0 bg-zinc-950/30 backdrop-blur-[1px]" onClick={onClose} />
      <aside role="dialog" aria-label="Request trace" className="animate-fade-in relative flex h-full w-full max-w-lg flex-col bg-white shadow-2xl">
        <header className="flex items-start justify-between border-b border-zinc-200 px-5 py-4">
          <div>
            <h2 className="text-sm font-semibold text-zinc-900">Request trace</h2>
            <p className="mt-0.5 font-mono text-xs text-zinc-500">{requestId}</p>
          </div>
          <button type="button" aria-label="Close" onClick={onClose} className="rounded-md p-1 text-zinc-500 hover:bg-zinc-100">
            <X className="size-4" />
          </button>
        </header>
        <div className="scroll-thin flex-1 overflow-y-auto px-5 py-4">
          {error && <Callout tone="error">{error}</Callout>}
          {!trace && !error && (
            <p className="flex items-center gap-2 text-sm text-zinc-500">
              <Loader2 className="size-4 animate-spin" /> Loading trace…
            </p>
          )}
          {trace && (
            <>
              <div className="mb-5 grid grid-cols-3 gap-2 text-center">
                {[
                  ["Status", trace.status],
                  ["Latency", `${((trace.latency_ms ?? 0) / 1000).toFixed(1)} s`],
                  ["Billed", `$${trace.billed_cost_usd.toFixed(5)}`],
                ].map(([k, v]) => (
                  <div key={k} className="rounded-lg border border-zinc-200 px-2 py-2">
                    <div className="text-[11px] text-zinc-500">{k}</div>
                    <div className="text-sm font-semibold text-zinc-900">{v}</div>
                  </div>
                ))}
              </div>
              {trace.error && <Callout tone="error">Error: {trace.error}</Callout>}
              <ol className="relative space-y-4 border-l border-zinc-200 pl-5">
                {trace.steps.map((s) => {
                  const meta = STEP_META[s.kind] ?? { icon: Workflow, title: s.kind };
                  const Icon = meta.icon;
                  const bad =
                    (s.kind === "validator" && s.payload.stage !== "ok") ||
                    (s.kind === "llm" && s.payload.status !== "ok" && s.payload.status !== "cached");
                  return (
                    <li key={s.step_no} className="relative">
                      <span
                        className={clsx(
                          "absolute top-0.5 -left-[31px] flex size-5 items-center justify-center rounded-full ring-4 ring-white",
                          bad ? "bg-amber-100 text-amber-700" : "bg-brand-50 text-brand-700",
                        )}
                      >
                        <Icon className="size-3" />
                      </span>
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium text-zinc-900">{meta.title}</span>
                        {s.ms != null && <Badge>{s.ms} ms</Badge>}
                      </div>
                      <p className="mt-0.5 text-xs break-words text-zinc-600">{summary(s)}</p>
                    </li>
                  );
                })}
              </ol>
            </>
          )}
        </div>
      </aside>
    </div>
  );
}
