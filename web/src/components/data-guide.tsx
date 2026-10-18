// "Explore the data": what the dataset contains and what can be asked. Everything comes
// from GET /v1/catalog (fixed read-only queries and the glossary; no model call).
"use client";

import clsx from "clsx";
import {
  ArrowRight,
  Ban,
  BookOpen,
  Boxes,
  ChartLine,
  ChevronDown,
  Loader2,
  MessageCircleQuestion,
  PackageSearch,
  Search,
  ShoppingCart,
  Star,
  Store,
  Truck,
  Users,
  X,
} from "lucide-react";
import { useEffect, useState } from "react";
import { formatMonth, humanize, plural } from "@/lib/format";
import type { Catalog } from "@/lib/types";
import { DataTimeline } from "./data-timeline";
import { Callout, SectionTitle, Tabs } from "./ui";

type Tab = "overview" | "tables" | "definitions";

const TOPIC_ICONS: Record<string, typeof Truck> = {
  Sales: ShoppingCart,
  Delivery: Truck,
  Customers: Users,
  Sellers: Store,
  Reviews: Star,
  Products: PackageSearch,
};

const month = (m: string | null | undefined) => (m ? formatMonth(m) : "—");

function Stat({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded-lg border border-zinc-200 px-3 py-2.5">
      <div className="text-[11px] font-medium text-zinc-500">{label}</div>
      <div className="mt-0.5 text-lg font-semibold text-zinc-900 tabular-nums">
        {typeof value === "number" ? value.toLocaleString("en-US") : value}
      </div>
    </div>
  );
}

type Section = { title: string; text: string; steps?: string[] };

/** One overview section; "Sales: ..." style sentences become a short labelled list. */
function OverviewSection({ section }: { section: Section }) {
  const parts = section.text.split(/(?<=\.)\s+(?=[A-Z][a-z]+: )/);
  const labelled = parts.length > 1 && parts.every((p) => /^[A-Z][a-z]+: /.test(p));
  return (
    <section>
      <h3 className="mb-1.5 text-sm font-semibold text-zinc-900">{section.title}</h3>
      {section.steps && (
        <ol aria-label="Order steps" className="mb-3 flex flex-wrap items-center gap-1.5 text-xs">
          {section.steps.map((step, i) => (
            <li key={step} className="flex items-center gap-1.5">
              <span className="flex items-center gap-1.5 rounded-full border border-brand-100 bg-brand-50 px-2.5 py-1 font-medium text-brand-700">
                <span className="flex size-4 items-center justify-center rounded-full bg-brand-600 text-[10px] text-white">{i + 1}</span>
                {step}
              </span>
              {i < section.steps!.length - 1 && <ArrowRight className="size-3 text-zinc-400" aria-hidden="true" />}
            </li>
          ))}
        </ol>
      )}
      {labelled ? (
        <ul className="space-y-1.5">
          {parts.map((p) => {
            const [label, ...rest] = p.split(": ");
            return (
              <li key={label} className="text-[14px] leading-relaxed text-zinc-700">
                <b className="font-medium text-zinc-900">{label}:</b> {rest.join(": ")}
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="text-[14px] leading-relaxed text-zinc-700">{section.text}</p>
      )}
    </section>
  );
}

function Overview({ catalog, onAsk }: { catalog: Catalog; onAsk: (q: string) => void }) {
  const f = catalog.facts;
  const sections = catalog.dataset.overview ?? [];
  const [lead, ...rest] = sections;
  return (
    <div className="space-y-6">
      <div>
        {lead ? (
          <OverviewSection section={lead} />
        ) : (
          <p className="text-[14.5px] leading-relaxed text-zinc-700">{catalog.dataset.description}</p>
        )}
        <p className="mt-1.5 text-xs text-zinc-500">Source: {catalog.dataset.source}</p>
      </div>

      <div className="grid grid-cols-3 gap-2">
        <Stat label="Orders" value={f.orders} />
        <Stat label="Customers" value={f.customers} />
        <Stat label="Sellers" value={f.sellers} />
        <Stat label="Products" value={f.products} />
        <Stat label="Categories" value={f.categories} />
        <Stat label="Customer states" value={f.customer_states} />
      </div>

      {rest.slice(0, 1).map((s) => (
        <OverviewSection key={s.title} section={s} />
      ))}

      <div>
        <SectionTitle>Orders per month</SectionTitle>
        <DataTimeline facts={f} />
      </div>

      <div className="space-y-1.5 rounded-lg bg-zinc-50 px-4 py-3 text-sm text-zinc-700">
        <p>
          <b className="font-medium text-zinc-900">The data runs from</b> {month(f.first_month)} to {month(f.last_month)}. Totals
          (&ldquo;revenue in 2016&rdquo;, &ldquo;all orders&rdquo;) use every month.
        </p>
        {f.analysis_window && (
          <p>
            <b className="font-medium text-zinc-900">Trends and monthly comparisons use</b> {month(f.analysis_window.start)} to{" "}
            {month(f.analysis_window.end)}: the months before and after have so few orders that a trend through them would
            mislead.
          </p>
        )}
        <p>
          <b className="font-medium text-zinc-900">&ldquo;Today&rdquo;</b> means the end of the data, so &ldquo;last month&rdquo; is the
          last full month in it.
        </p>
        {f.partial_months.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5 pt-1">
            <span className="text-xs text-zinc-500">Partial months:</span>
            {f.partial_months.map((p) => (
              <span key={p.month} className="rounded bg-amber-50 px-1.5 py-0.5 text-[11px] text-amber-800 ring-1 ring-amber-100 ring-inset">
                {month(p.month)} · {plural(p.orders, "order")}
              </span>
            ))}
          </div>
        )}
      </div>

      {rest.slice(1).map((s) => (
        <OverviewSection key={s.title} section={s} />
      ))}

      <div>
        <SectionTitle>Things you can ask</SectionTitle>
        <div className="space-y-3">
          {catalog.examples.map((e) => {
            const Icon = TOPIC_ICONS[e.topic] ?? MessageCircleQuestion;
            return (
              <div key={e.topic}>
                <div className="mb-1.5 flex items-center gap-1.5 text-sm font-medium text-zinc-900">
                  <Icon className="size-4 text-brand-600" /> {e.topic}
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {e.questions.map((q) => (
                    <button
                      key={q}
                      type="button"
                      onClick={() => onAsk(q)}
                      className="rounded-full border border-zinc-200 bg-white px-3 py-1 text-left text-[13px] text-zinc-700 transition hover:border-brand-500 hover:text-brand-700"
                    >
                      {q}
                    </button>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      <div>
        <SectionTitle>What it cannot answer</SectionTitle>
        <ul className="space-y-1.5">
          {catalog.limits.map((l) => (
            <li key={l} className="flex gap-2 text-sm text-zinc-700">
              <Ban className="mt-0.5 size-3.5 shrink-0 text-zinc-400" /> {l}
            </li>
          ))}
        </ul>
      </div>

      {(catalog.missing_fields ?? []).length > 0 && (
        <div>
          <SectionTitle>Not in the data, and what to use instead</SectionTitle>
          <dl className="divide-y divide-zinc-100 rounded-lg border border-zinc-200 text-sm">
            {catalog.missing_fields.map((m) => (
              <div key={m.field} className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)] gap-3 px-4 py-2">
                <dt className="text-zinc-500 line-through decoration-zinc-300">{m.field}</dt>
                <dd className="text-zinc-800">{m.closest}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}
    </div>
  );
}

function Tables({ catalog }: { catalog: Catalog }) {
  const [open, setOpen] = useState<string | null>("orders");
  return (
    <div className="space-y-2">
      <p className="mb-3 text-sm text-zinc-600">
        The agent reads these {catalog.views.length} tables (read-only views over the raw data). Every question is answered with SQL over them.
      </p>
      {catalog.views.map((v) => (
        <div key={v.name} className="rounded-lg border border-zinc-200">
          <button
            type="button"
            aria-expanded={open === v.name}
            onClick={() => setOpen(open === v.name ? null : v.name)}
            className="flex w-full items-start gap-3 px-4 py-3 text-left"
          >
            <Boxes className="mt-0.5 size-4 shrink-0 text-zinc-400" />
            <span className="min-w-0 flex-1">
              <span className="block font-mono text-sm font-medium text-zinc-900">{v.name}</span>
              <span className="mt-0.5 block text-xs leading-relaxed text-zinc-600">{v.description}</span>
            </span>
            <span className="shrink-0 text-xs text-zinc-400">{v.columns.length} columns</span>
            <ChevronDown className={clsx("mt-0.5 size-4 shrink-0 text-zinc-400 transition-transform", open !== v.name && "-rotate-90")} />
          </button>
          {open === v.name && (
            <dl className="divide-y divide-zinc-100 border-t border-zinc-100">
              {v.columns.map((c) => (
                <div key={c} className="grid grid-cols-[minmax(0,180px)_minmax(0,1fr)] gap-3 px-4 py-1.5">
                  <dt className="truncate font-mono text-[12px] text-zinc-800" title={c}>
                    {c}
                  </dt>
                  <dd className="text-xs leading-relaxed text-zinc-500">{v.column_notes?.[c] || humanize(c)}</dd>
                </div>
              ))}
            </dl>
          )}
        </div>
      ))}
    </div>
  );
}

function Definitions({ catalog }: { catalog: Catalog }) {
  const [q, setQ] = useState("");
  const needle = q.trim().toLowerCase();
  const shown = catalog.definitions.filter(
    (d) => !needle || d.term.toLowerCase().includes(needle) || d.definition.toLowerCase().includes(needle),
  );
  return (
    <div>
      <label className="relative mb-3 block">
        <span className="sr-only">Search definitions</span>
        <Search className="absolute top-2.5 left-3 size-4 text-zinc-400" />
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search, e.g. late, revenue, customer"
          className="h-9 w-full rounded-lg border border-zinc-300 pr-3 pl-9 text-sm outline-none focus:border-brand-500 focus:ring-4 focus:ring-brand-100"
        />
      </label>
      <p className="mb-3 text-xs text-zinc-500">The same business definitions the agent follows when it writes queries.</p>
      <dl className="divide-y divide-zinc-100 rounded-lg border border-zinc-200">
        {shown.map((d) => (
          <div key={d.term} className="px-4 py-2.5">
            <dt className="text-sm font-medium text-zinc-900">{d.term}</dt>
            <dd className="mt-0.5 text-[13px] leading-relaxed text-zinc-600">{d.definition}</dd>
          </div>
        ))}
        {shown.length === 0 && <p className="px-4 py-3 text-sm text-zinc-500">No definition matches &ldquo;{q}&rdquo;.</p>}
      </dl>
    </div>
  );
}

export function DataGuide({
  open,
  catalog,
  error,
  onClose,
  onAsk,
}: {
  open: boolean;
  catalog: Catalog | null;
  error: string | null;
  onClose: () => void;
  onAsk: (question: string) => void;
}) {
  const [tab, setTab] = useState<Tab>("overview");

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <button type="button" aria-label="Close data guide" className="absolute inset-0 bg-zinc-950/30 backdrop-blur-[1px]" onClick={onClose} />
      <aside role="dialog" aria-label="Explore the data" className="animate-fade-in relative flex h-full w-full max-w-2xl flex-col bg-white shadow-2xl">
        <header className="flex items-start justify-between px-5 pt-5 pb-3">
          <div className="flex items-start gap-3">
            <span className="flex size-9 items-center justify-center rounded-lg bg-brand-50 text-brand-600">
              <BookOpen className="size-4.5" />
            </span>
            <div>
              <h2 className="text-base font-semibold text-zinc-900">Explore the data</h2>
              <p className="text-xs text-zinc-500">{catalog?.dataset.name ?? "What you can ask about"}</p>
            </div>
          </div>
          <button type="button" aria-label="Close" onClick={onClose} className="rounded-md p-1 text-zinc-500 hover:bg-zinc-100">
            <X className="size-4" />
          </button>
        </header>
        <Tabs<Tab>
          value={tab}
          onChange={setTab}
          tabs={[
            { id: "overview", label: "Overview" },
            { id: "tables", label: "Tables", count: catalog?.views.length },
            { id: "definitions", label: "Definitions", count: catalog?.definitions.length },
          ]}
        />
        <div className="scroll-thin flex-1 overflow-y-auto px-5 py-5">
          {error && <Callout tone="error">{error}</Callout>}
          {!catalog && !error && (
            <p className="flex items-center gap-2 text-sm text-zinc-500">
              <Loader2 className="size-4 animate-spin" /> Loading…
            </p>
          )}
          {catalog && tab === "overview" && <Overview catalog={catalog} onAsk={onAsk} />}
          {catalog && tab === "tables" && <Tables catalog={catalog} />}
          {catalog && tab === "definitions" && <Definitions catalog={catalog} />}
        </div>
        <footer className="flex items-center gap-2 border-t border-zinc-100 px-5 py-3 text-xs text-zinc-500">
          <ChartLine className="size-3.5" /> Counts are computed from the data itself; opening this guide costs nothing.
        </footer>
      </aside>
    </div>
  );
}
