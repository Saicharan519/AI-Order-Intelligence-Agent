"use client";

import clsx from "clsx";
import {
  AlertTriangle,
  ArrowUpRight,
  BookOpen,
  Database,
  Check,
  CircleHelp,
  Copy,
  Info,
  MessageSquareText,
  ScanSearch,
  ShieldCheck,
  Sparkles,
  Workflow,
} from "lucide-react";
import { useState } from "react";
import { STATUS_MESSAGES, formatCell, humanize, scopeLines, usageParts } from "@/lib/format";
import type { AskResponse, Component } from "@/lib/types";
import { DataTimeline } from "../data-timeline";
import { Badge, Button, Callout, Card, Disclosure, SectionTitle, Tabs } from "../ui";
import { DataTable } from "./data-table";
import { EvidenceList } from "./evidence-list";
import { InvestigationReport } from "./report";
import { ResultChart } from "./result-chart";

type Tab = "overview" | "evidence" | "scope";

function ValueTiles({ columns, row }: { columns: string[]; row: unknown[] }) {
  return (
    <div className={clsx("grid gap-3", columns.length > 1 ? "sm:grid-cols-2 lg:grid-cols-3" : "")}>
      {columns.map((c, i) => {
        const text = formatCell(c, typeof row[i] === "string" && /^-?\d+(\.\d+)?$/.test(row[i] as string) ? Number(row[i]) : row[i]);
        const long = text.length > 14;
        return (
          <div key={c} className="min-w-0 rounded-lg border border-zinc-200 bg-gradient-to-b from-white to-zinc-50/60 px-4 py-3">
            <div className="text-xs font-medium text-zinc-500">{humanize(c)}</div>
            <div
              title={text}
              className={clsx(
                "mt-1 font-semibold tracking-tight break-all text-zinc-900",
                long ? "font-mono text-sm" : "text-3xl tabular-nums",
              )}
            >
              {text}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function ComponentView({ comp, table, filename }: { comp: Component; table?: Extract<Component, { type: "table" }>; filename: string }) {
  if (comp.type === "text" && "variant" in comp && comp.variant === "answer_card" && "row" in comp) {
    return <ValueTiles columns={comp.columns} row={comp.row} />;
  }
  if (comp.type === "text" && "text" in comp) return <p className="text-[15px] leading-relaxed text-zinc-700">{comp.text}</p>;
  if (comp.type === "table") return <DataTable columns={comp.columns} rows={comp.rows} filename={filename} />;
  if (comp.type === "chart" && table) {
    return (
      <div className="rounded-lg border border-zinc-200 p-3 pt-4">
        <ResultChart kind={comp.kind} x={comp.x} y={comp.y} columns={table.columns} rows={table.rows} />
      </div>
    );
  }
  if (comp.type === "report") {
    return <InvestigationReport verdict={comp.verdict} topDriver={comp.top_driver} findings={comp.findings} />;
  }
  return null;
}

function CopyId({ id }: { id: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      title="Copy the full request id"
      onClick={async () => {
        await navigator.clipboard?.writeText(id);
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      }}
      className="inline-flex items-center gap-1 font-mono hover:text-zinc-800"
    >
      {copied ? <Check className="size-3" /> : <Copy className="size-3" />}
      {id.slice(0, 8)}
    </button>
  );
}

function UsageFooter({ result, onTrace }: { result: AskResponse; onTrace: (requestId: string) => void }) {
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-zinc-100 bg-zinc-50/70 px-5 py-2.5 text-xs text-zinc-500">
      {usageParts(result.usage).map((p) => (
        <span key={p}>{p}</span>
      ))}
      <span className="ml-auto flex items-center gap-3">
        <CopyId id={result.request_id} />
        <button type="button" onClick={() => onTrace(result.request_id)} className="font-medium text-brand-600 hover:text-brand-700">
          View trace
        </button>
      </span>
    </div>
  );
}

/** A refused question: why, where to look, and questions that can be answered instead. */
function RefusalCard({
  result,
  suggestions,
  onFollowup,
  onTrace,
  onOpenGuide,
}: {
  result: AskResponse;
  suggestions: string[];
  onFollowup: (question: string) => void;
  onTrace: (requestId: string) => void;
  onOpenGuide: () => void;
}) {
  const reason = result.notes[0] ?? result.headline;
  return (
    <Card className="animate-fade-in overflow-hidden">
      <div className="space-y-4 p-5">
        <div>
          <Badge icon={<Info className="size-3" />}>Out of scope</Badge>
          <h2 className="mt-2.5 text-lg leading-snug font-semibold text-zinc-900">That&apos;s outside what I can answer</h2>
          <p className="mt-1 text-sm leading-relaxed text-zinc-600">{reason}</p>
        </div>
        <div className="rounded-lg border border-brand-100 bg-brand-50/60 p-4">
          <p className="text-sm text-zinc-800">
            I answer questions about the Olist order data: sales, deliveries, customers, sellers, reviews and products.
          </p>
          <Button variant="primary" size="sm" className="mt-3" onClick={onOpenGuide}>
            <BookOpen className="size-3.5" /> Explore the data
          </Button>
        </div>
        {suggestions.length > 0 && (
          <div>
            <SectionTitle>Try one of these instead</SectionTitle>
            <div className="flex flex-wrap gap-2">
              {suggestions.map((q) => (
                <button
                  key={q}
                  type="button"
                  onClick={() => onFollowup(q)}
                  className="group inline-flex items-center gap-1.5 rounded-full border border-zinc-200 bg-white px-3 py-1.5 text-sm text-zinc-700 transition hover:border-brand-500 hover:text-brand-700"
                >
                  {q}
                  <ArrowUpRight className="size-3.5 text-zinc-400 group-hover:text-brand-600" />
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
      <UsageFooter result={result} onTrace={onTrace} />
    </Card>
  );
}

/** "What is this dataset?": answered in code from the catalog, without a model call. */
function AboutCard({
  result,
  onFollowup,
  onTrace,
  onOpenGuide,
}: {
  result: AskResponse;
  onFollowup: (question: string) => void;
  onTrace: (requestId: string) => void;
  onOpenGuide: () => void;
}) {
  const about = result.components.find((c): c is Extract<Component, { type: "about" }> => c.type === "about");
  const sample = result.components.find((c): c is Extract<Component, { type: "table" }> => c.type === "table");
  if (!about) return null;
  const f = about.facts;
  const stats: [string, number][] = [
    ["Orders", f.orders],
    ["Customers", f.customers],
    ["Sellers", f.sellers],
    ["Products", f.products],
    ["Categories", f.categories],
    ["States", f.customer_states],
  ];
  return (
    <Card className="animate-fade-in overflow-hidden">
      <div className="space-y-5 p-5">
        <div>
          <Badge tone="brand" icon={<Database className="size-3" />}>About the data</Badge>
          <h2 className="mt-2.5 text-lg leading-snug font-semibold text-balance text-zinc-900">{result.headline}</h2>
          <p className="mt-1 text-sm leading-relaxed text-zinc-600">{about.dataset.description}</p>
        </div>
        <div className="grid grid-cols-3 gap-2 sm:grid-cols-6">
          {stats.map(([label, value]) => (
            <div key={label} className="rounded-lg border border-zinc-200 px-3 py-2">
              <div className="text-[11px] text-zinc-500">{label}</div>
              <div className="text-base font-semibold text-zinc-900 tabular-nums">{value.toLocaleString("en-US")}</div>
            </div>
          ))}
        </div>
        <div>
          <SectionTitle>Orders per month</SectionTitle>
          <DataTimeline facts={f} />
        </div>
        <div>
          <SectionTitle>The tables the agent reads</SectionTitle>
          <ul className="grid gap-2 sm:grid-cols-2">
            {about.views.map((v) => (
              <li key={v.name} className="rounded-lg border border-zinc-200 px-3 py-2">
                <div className="font-mono text-[13px] font-medium text-zinc-900">{v.name}</div>
                <div className="mt-0.5 text-xs leading-relaxed text-zinc-600">{v.description}</div>
              </li>
            ))}
          </ul>
        </div>
        {sample && (
          <div>
            <SectionTitle>Five example orders</SectionTitle>
            <DataTable columns={sample.columns} rows={sample.rows} download={false} />
          </div>
        )}
        <div>
          <SectionTitle>Try asking</SectionTitle>
          <div className="flex flex-wrap gap-2">
            {about.examples.map((e) => (
              <button
                key={e.topic}
                type="button"
                onClick={() => onFollowup(e.questions[0])}
                className="group inline-flex items-center gap-1.5 rounded-full border border-zinc-200 bg-white px-3 py-1.5 text-sm text-zinc-700 transition hover:border-brand-500 hover:text-brand-700"
              >
                <span className="text-xs text-zinc-400">{e.topic}</span> {e.questions[0]}
                <ArrowUpRight className="size-3.5 text-zinc-400 group-hover:text-brand-600" />
              </button>
            ))}
          </div>
        </div>
        <Button variant="primary" size="sm" onClick={onOpenGuide}>
          <BookOpen className="size-3.5" /> Open the full data guide
        </Button>
      </div>
      <UsageFooter result={result} onTrace={onTrace} />
    </Card>
  );
}

export function AnswerCard({
  result,
  onFollowup,
  onTrace,
  onOpenGuide = () => {},
  suggestions = [],
}: {
  result: AskResponse;
  onFollowup: (question: string) => void;
  onTrace: (requestId: string) => void;
  onOpenGuide?: () => void;
  suggestions?: string[];
}) {
  const [tab, setTab] = useState<Tab>("overview");
  if (result.route === "about") {
    return <AboutCard result={result} onFollowup={onFollowup} onTrace={onTrace} onOpenGuide={onOpenGuide} />;
  }
  if (result.route === "refuse") {
    return (
      <RefusalCard result={result} suggestions={suggestions} onFollowup={onFollowup} onTrace={onTrace} onOpenGuide={onOpenGuide} />
    );
  }
  const comps = result.components ?? [];
  const table = comps.find((c): c is Extract<Component, { type: "table" }> => c.type === "table");
  // A chart reads better above its table.
  const ordered = [...comps].sort((a, b) => (a.type === "chart" ? -1 : 0) - (b.type === "chart" ? -1 : 0));
  const status = STATUS_MESSAGES[result.status];
  const investigate = result.route === "investigate";
  const validated = result.evidence.filter((e) => e.validator?.ok).length;
  const scope = scopeLines(result.scope);
  const filename = `orderintel-${result.request_id.slice(0, 8)}.csv`;

  return (
    <Card className="animate-fade-in overflow-hidden">
      <div className="px-5 pt-5 pb-4">
        <div className="mb-2.5 flex flex-wrap items-center gap-1.5">
          {investigate ? (
            <Badge tone="brand" icon={<ScanSearch className="size-3" />}>Investigation</Badge>
          ) : result.route === "answer" ? (
            <Badge tone="brand" icon={<MessageSquareText className="size-3" />}>Answer</Badge>
          ) : result.route === "clarify" ? (
            <Badge tone="warn" icon={<CircleHelp className="size-3" />}>Needs clarification</Badge>
          ) : (
            <Badge icon={<Info className="size-3" />}>Out of scope</Badge>
          )}
          {result.grounding.numbers_checked > 0 && result.grounding.untraced.length === 0 && (
            <Badge tone="good" icon={<ShieldCheck className="size-3" />}>
              {result.grounding.numbers_checked} numbers traced to data
            </Badge>
          )}
          {validated > 0 && (
            <Badge icon={<Workflow className="size-3" />}>
              {validated} validated quer{validated === 1 ? "y" : "ies"}
            </Badge>
          )}
        </div>
        <h2 className="text-lg leading-snug font-semibold text-balance text-zinc-900">{result.headline}</h2>
      </div>

      <Tabs<Tab>
        value={tab}
        onChange={setTab}
        tabs={[
          { id: "overview", label: "Overview" },
          { id: "evidence", label: "Evidence", count: result.evidence.length },
          { id: "scope", label: "Scope & definitions" },
        ]}
      />

      <div className="space-y-5 p-5">
        {tab === "overview" && (
          <>
            {status && (
              <Callout tone={status[0]} icon={status[0] === "error" ? <AlertTriangle className="size-4" /> : <Info className="size-4" />}>
                {status[1]}
              </Callout>
            )}
            {result.warnings.map((w) => (
              <Callout key={w} tone="warn" icon={<AlertTriangle className="size-4" />}>{w}</Callout>
            ))}
            {result.grounding.untraced.length > 0 && (
              <Callout tone="warn" icon={<AlertTriangle className="size-4" />}>
                Some numbers in this answer could not be traced to the query results: {result.grounding.untraced.join(", ")}
              </Callout>
            )}
            {ordered.map((c, i) => (
              <ComponentView key={i} comp={c} table={table} filename={filename} />
            ))}
            {result.notes.length > 0 && (
              <div>
                <SectionTitle>{investigate ? "Findings" : "Key points"}</SectionTitle>
                <ul className="space-y-2">
                  {result.notes.map((n) => (
                    <li key={n} className="flex gap-2.5 text-[14.5px] leading-relaxed text-zinc-700">
                      <Sparkles className="mt-1 size-3.5 shrink-0 text-brand-500" />
                      <span>{n}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {result.caveats.length > 0 && (
              <Disclosure title={`Caveats (${result.caveats.length})`}>
                <ul className="list-disc space-y-1 pl-5 text-xs leading-relaxed text-zinc-600">
                  {result.caveats.map((c) => (
                    <li key={c}>{c}</li>
                  ))}
                </ul>
              </Disclosure>
            )}
            {result.followups.length > 0 && (
              <div>
                <SectionTitle>Suggested follow-ups</SectionTitle>
                <div className="flex flex-wrap gap-2">
                  {result.followups.map((f) => (
                    <button
                      key={f.question}
                      type="button"
                      onClick={() => onFollowup(f.question)}
                      className="group inline-flex items-center gap-1.5 rounded-full border border-zinc-200 bg-white px-3 py-1.5 text-sm text-zinc-700 transition hover:border-brand-500 hover:text-brand-700"
                    >
                      {f.label}
                      {f.inherits_scope && <span className="text-xs text-zinc-400">· keeps scope</span>}
                      <ArrowUpRight className="size-3.5 text-zinc-400 group-hover:text-brand-600" />
                    </button>
                  ))}
                </div>
              </div>
            )}
          </>
        )}

        {tab === "evidence" && <EvidenceList evidence={result.evidence} columns={table?.columns} />}

        {tab === "scope" && (
          <div className="space-y-4">
            {scope.length === 0 && <p className="text-sm text-zinc-500">No scope was recorded for this answer.</p>}
            <dl className="divide-y divide-zinc-100 rounded-lg border border-zinc-200">
              {scope.map((l, i) => (
                <div key={i} className="grid grid-cols-[110px_1fr] gap-3 px-4 py-2.5 text-sm">
                  <dt className="font-medium text-zinc-500">{l.label}</dt>
                  <dd className="text-zinc-800">{l.text}</dd>
                </div>
              ))}
            </dl>
            {result.scope.partial_period_warnings.map((w) => (
              <Callout key={w} tone="warn" icon={<AlertTriangle className="size-4" />}>{w}</Callout>
            ))}
          </div>
        )}
      </div>

      <UsageFooter result={result} onTrace={onTrace} />
    </Card>
  );
}
