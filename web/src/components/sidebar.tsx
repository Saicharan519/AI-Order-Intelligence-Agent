"use client";

import clsx from "clsx";
import { History, Loader2, LogOut, MessageSquare, Plus, Shield, Wallet } from "lucide-react";
import Link from "next/link";
import type { Budget, Health, SessionSummary, UserInfo } from "@/lib/types";
import { Logo } from "./ui";

/** Group conversations by when they were last used, newest first. */
export function groupByDate(items: SessionSummary[], now = new Date()): [string, SessionSummary[]][] {
  const day = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const today = day(now);
  const groups = new Map<string, SessionSummary[]>();
  for (const s of items) {
    const age = Math.round((today - day(new Date(s.updated_at))) / 86_400_000);
    const label = age <= 0 ? "Today" : age === 1 ? "Yesterday" : age <= 7 ? "Previous 7 days" : "Older";
    groups.set(label, [...(groups.get(label) ?? []), s]);
  }
  return [...groups.entries()];
}

function timeOf(iso: string): string {
  const d = new Date(iso);
  const sameDay = d.toDateString() === new Date().toDateString();
  return sameDay
    ? d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    : d.toLocaleDateString([], { day: "numeric", month: "short" });
}

export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  return ((parts[0]?.[0] ?? "?") + (parts.length > 1 ? parts.at(-1)![0] : "")).toUpperCase();
}

/** A user sees their own daily budget; an admin sees the project's overall budget. */
function BudgetMeter({ budget }: { budget: Budget }) {
  const mine = budget.you;
  const spent = mine ? mine.today_usd : budget.total_usd;
  const cap = mine ? mine.daily_cap_usd : budget.total_cap_usd;
  const used = cap > 0 ? Math.min(spent / cap, 1) : 1;
  return (
    <div>
      <div className="mb-1.5 flex items-center justify-between text-xs">
        <span className="flex items-center gap-1.5 text-zinc-400">
          <Wallet className="size-3.5" /> {mine ? "Your budget today" : "Model budget"}
        </span>
        <span className="font-medium text-zinc-200 tabular-nums">
          ${spent.toFixed(4)} / ${cap.toFixed(2)}
        </span>
      </div>
      <div
        className="h-1.5 overflow-hidden rounded-full bg-zinc-800"
        role="progressbar"
        aria-label="Budget used"
        aria-valuenow={Math.round(used * 100)}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <div className={clsx("h-full rounded-full", used > 0.8 ? "bg-rose-500" : "bg-brand-500")} style={{ width: `${Math.max(used * 100, 1.5)}%` }} />
      </div>
      <div className="mt-1 text-[11px] text-zinc-500 tabular-nums">
        {mine ? "Resets at midnight UTC" : `Today $${budget.today_usd.toFixed(4)} of $${budget.daily_cap_usd.toFixed(2)}`}
      </div>
    </div>
  );
}

function StatusDot({ health }: { health: Health | null | "down" }) {
  const up = health && health !== "down" && health.database === "ok";
  const text =
    health === null ? "Checking…" : health === "down" ? "API unreachable" : health.database === "ok" ? (health.llm_enabled ? "All systems normal" : "Questions paused") : "Database unavailable";
  const color = health === null ? "bg-zinc-500" : up && health.llm_enabled ? "bg-emerald-400" : up ? "bg-amber-400" : "bg-rose-500";
  return (
    <span className="flex items-center gap-2 text-xs text-zinc-400">
      <span className="relative flex size-2">
        {up && <span className={clsx("absolute inline-flex size-full animate-ping rounded-full opacity-60", color)} />}
        <span className={clsx("relative inline-flex size-2 rounded-full", color)} />
      </span>
      {text}
    </span>
  );
}

export function Sidebar({
  sessions,
  currentId,
  pendingId,
  loading,
  onOpen,
  onNew,
  budget,
  health,
  user,
  onSignOut,
}: {
  sessions: SessionSummary[] | null;
  currentId: string | null;
  pendingId: string | null;
  loading: boolean;
  onOpen: (sessionId: string) => void;
  onNew: () => void;
  budget: Budget | null;
  health: Health | null | "down";
  user: UserInfo | null;
  onSignOut: () => void;
}) {
  return (
    <aside className="flex h-full w-72 shrink-0 flex-col bg-zinc-950 text-zinc-300">
      <div className="flex items-center gap-2.5 px-5 pt-5 pb-4">
        <Logo className="size-8" />
        <div className="leading-tight">
          <div className="text-sm font-semibold text-white">Order Intelligence</div>
          <div className="text-[11px] text-zinc-500">Analytics agent · Olist</div>
        </div>
      </div>

      <div className="px-3">
        <button
          type="button"
          onClick={onNew}
          className="flex w-full items-center gap-2 rounded-lg border border-zinc-800 bg-zinc-900 px-3 py-2 text-sm font-medium text-zinc-100 transition hover:border-zinc-700 hover:bg-zinc-800"
        >
          <Plus className="size-4" /> New analysis
        </button>
      </div>

      <nav aria-label="Conversations" className="scroll-dark mt-5 flex-1 overflow-y-auto px-3">
        {sessions === null && (
          <p className="flex items-center gap-2 px-2 py-1 text-xs text-zinc-500">
            <Loader2 className="size-3 animate-spin" /> Loading history…
          </p>
        )}
        {sessions?.length === 0 && (
          <p className="flex items-start gap-2 px-2 py-1 text-xs leading-relaxed text-zinc-600">
            <History className="mt-0.5 size-3.5 shrink-0" /> Your conversations will be saved here.
          </p>
        )}
        {sessions &&
          groupByDate(sessions).map(([group, items]) => (
            <div key={group} className="mb-4">
              <div className="px-2 pb-1.5 text-[11px] font-semibold tracking-wider text-zinc-500 uppercase">{group}</div>
              <ul className="space-y-0.5">
                {items.map((s) => (
                  <li key={s.session_id}>
                    <button
                      type="button"
                      aria-current={currentId === s.session_id ? "true" : undefined}
                      onClick={() => onOpen(s.session_id)}
                      className={clsx(
                        "flex w-full items-start gap-2.5 rounded-md px-2 py-2 text-left transition",
                        currentId === s.session_id ? "bg-zinc-800 text-white" : "text-zinc-400 hover:bg-zinc-900 hover:text-zinc-200",
                      )}
                    >
                      {loading && currentId === s.session_id ? (
                        <Loader2 className="mt-0.5 size-3.5 shrink-0 animate-spin" />
                      ) : (
                        <MessageSquare className={clsx("mt-0.5 size-3.5 shrink-0", pendingId === s.session_id && "animate-pulse")} />
                      )}
                      <span className="min-w-0 flex-1">
                        <span className="line-clamp-1 text-[13px] [overflow-wrap:anywhere]">{s.title || "Untitled"}</span>
                        <span className="mt-0.5 block text-[11px] text-zinc-500">
                          {s.questions} question{s.questions === 1 ? "" : "s"} · {timeOf(s.updated_at)}
                        </span>
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          ))}
      </nav>

      <div className="space-y-3 border-t border-zinc-900 px-5 py-4">
        {budget && <BudgetMeter budget={budget} />}
        <StatusDot health={health} />
        {user && (
          <div className="flex items-center gap-2.5 rounded-lg bg-zinc-900 px-2.5 py-2">
            <span
              aria-hidden="true"
              className="flex size-8 shrink-0 items-center justify-center rounded-full bg-brand-600 text-xs font-semibold text-white"
            >
              {initials(user.name)}
            </span>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-[13px] font-medium text-zinc-100">{user.name}</span>
              <span className="block truncate text-[11px] text-zinc-500">{user.email}</span>
            </span>
            {user.role === "admin" && (
              <Link
                href="/admin"
                title="Admin: users and invites"
                aria-label="Admin"
                className="rounded-md p-1.5 text-zinc-400 hover:bg-zinc-800 hover:text-white"
              >
                <Shield className="size-4" />
              </Link>
            )}
            <button
              type="button"
              onClick={onSignOut}
              title="Sign out"
              aria-label="Sign out"
              className="rounded-md p-1.5 text-zinc-400 hover:bg-zinc-800 hover:text-white"
            >
              <LogOut className="size-4" />
            </button>
          </div>
        )}
      </div>
    </aside>
  );
}
