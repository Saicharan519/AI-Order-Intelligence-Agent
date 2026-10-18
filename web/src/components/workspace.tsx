"use client";

import {
  ArrowUp,
  BookOpen,
  CalendarRange,
  ChartLine,
  History,

  Layers,
  Loader2,
  PackageSearch,
  ScanSearch,
  ShieldCheck,
  Trophy,
  X,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { httpApi, type Api } from "@/lib/api";
import { errorMessage, newSessionId, scopeChips } from "@/lib/format";
import type { AskResponse, Budget, Catalog, Health, SessionSummary, UserInfo } from "@/lib/types";
import { AnswerCard } from "./answer/answer-card";
import { CatalogProvider } from "./catalog-context";
import { DataGuide } from "./data-guide";
import { Sidebar } from "./sidebar";
import { TraceDrawer } from "./trace-drawer";
import { Button, Callout, Card, Logo } from "./ui";

const MAX_CHARS = 500;

export const EXAMPLES = [
  { icon: Trophy, title: "Top 5 categories by revenue in 2017", hint: "Ranking · bar chart" },
  { icon: ChartLine, title: "How is the late-delivery rate trending?", hint: "Monthly trend · line chart" },
  { icon: ScanSearch, title: "Why was March 2018 so bad for deliveries?", hint: "Root-cause investigation" },
  { icon: PackageSearch, title: "Which 5 sellers had the most orders in 2018?", hint: "Seller ranking" },
];

interface Turn {
  id: string;
  question: string;
  result?: AskResponse;
  error?: string;
}

function EmptyState({ onPick, onOpenGuide }: { onPick: (q: string) => void; onOpenGuide: () => void }) {
  return (
    <div className="mx-auto w-full max-w-3xl px-6 pt-[12vh] pb-10">
      <div className="mb-8 text-center">
        <span className="mb-4 inline-flex items-center gap-1.5 rounded-full border border-brand-100 bg-brand-50 px-3 py-1 text-xs font-medium text-brand-700">
          <ShieldCheck className="size-3.5" /> Every number traced to a validated query
        </span>
        <h1 className="text-3xl font-semibold tracking-tight text-balance text-zinc-900 sm:text-4xl">
          What do you want to know about your orders?
        </h1>
        <p className="mx-auto mt-3 max-w-xl text-[15px] text-zinc-600">
          Ask in plain English. The agent writes read-only SQL, validates it, runs it, and explains the result with its evidence.
        </p>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        {EXAMPLES.map(({ icon: Icon, title, hint }) => (
          <button
            key={title}
            type="button"
            onClick={() => onPick(title)}
            className="group flex items-start gap-3 rounded-xl border border-zinc-200 bg-white p-4 text-left shadow-[0_1px_2px_rgba(0,0,0,0.04)] transition hover:-translate-y-0.5 hover:border-brand-500/40 hover:shadow-md"
          >
            <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-zinc-100 text-zinc-600 transition group-hover:bg-brand-50 group-hover:text-brand-600">
              <Icon className="size-4.5" />
            </span>
            <span>
              <span className="block text-sm font-medium text-zinc-900">{title}</span>
              <span className="mt-0.5 block text-xs text-zinc-500">{hint}</span>
            </span>
          </button>
        ))}
      </div>
      <div className="mt-5 text-center">
        <button
          type="button"
          onClick={onOpenGuide}
          className="inline-flex items-center gap-1.5 text-sm font-medium text-brand-600 hover:text-brand-700"
        >
          <BookOpen className="size-4" /> Not sure what to ask? Explore the data
        </button>
      </div>
      <div className="mt-6 flex flex-wrap justify-center gap-x-6 gap-y-2 text-xs text-zinc-500">
        <span className="flex items-center gap-1.5"><Layers className="size-3.5" /> 99,441 orders · 8 tables</span>
        <span className="flex items-center gap-1.5"><CalendarRange className="size-3.5" /> Sep 2016 – Oct 2018</span>
        <span className="flex items-center gap-1.5"><ShieldCheck className="size-3.5" /> Read-only, validated SQL</span>
      </div>
    </div>
  );
}

function PendingCard() {
  return (
    <Card className="animate-fade-in p-5">
      <div className="flex items-center gap-2.5 text-sm text-zinc-600">
        <Loader2 className="size-4 animate-spin text-brand-600" />
        Analysing: writing a query, validating it, running it, and checking every number…
      </div>
      <div className="mt-4 space-y-2.5">
        <div className="h-4 w-3/4 animate-pulse rounded bg-zinc-100" />
        <div className="h-4 w-1/2 animate-pulse rounded bg-zinc-100" />
        <div className="h-40 animate-pulse rounded-lg bg-zinc-50" />
      </div>
    </Card>
  );
}

export function Workspace({ api = httpApi }: { api?: Api }) {
  const router = useRouter();
  const [user, setUser] = useState<UserInfo | null>(null);
  const [health, setHealth] = useState<Health | null | "down">(null);
  const [budget, setBudget] = useState<Budget | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [pending, setPending] = useState(false);
  const [draft, setDraft] = useState("");
  const [scope, setScope] = useState<string[] | null>(null);
  const [traceId, setTraceId] = useState<string | null>(null);
  const [sessions, setSessions] = useState<SessionSummary[] | null>(null);
  const [currentId, setCurrentId] = useState<string | null>(null);
  const [opening, setOpening] = useState(false);
  const [reopened, setReopened] = useState<{ expired: boolean } | null>(null);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const [guideOpen, setGuideOpen] = useState(false);
  // Created on first use (in an event handler), never during the server prerender.
  const session = useRef("");
  const sessionId = () => (session.current ||= newSessionId());
  const input = useRef<HTMLTextAreaElement>(null);

  const refreshBudget = useCallback(async () => {
    const r = await api.budget();
    if (r.ok) setBudget(r.data);
  }, [api]);

  const loadCatalog = useCallback(async () => {
    const r = await api.catalog();
    if (r.ok) {
      setCatalog(r.data);
      setCatalogError(null);
    } else setCatalogError(errorMessage(r.code));
  }, [api]);

  const openGuide = () => {
    setGuideOpen(true);
    if (!catalog) loadCatalog();
  };

  const refreshSessions = useCallback(async () => {
    const r = await api.sessions();
    setSessions(r.ok ? r.data.sessions : []);
  }, [api]);

  // Who is signed in; anyone else is sent to the sign-in page.
  useEffect(() => {
    api.me().then((r) => {
      if (!r.ok) {
        if (r.status === 401) router.replace("/login");
        return;
      }
      setUser(r.data);
      refreshBudget();
      refreshSessions();
      loadCatalog();
    });
    const ping = () => api.health().then((r) => setHealth(r.ok ? r.data : "down"));
    ping();
    const t = setInterval(ping, 30_000);
    return () => clearInterval(t);
  }, [api, router, refreshBudget, refreshSessions, loadCatalog]);

  const signOut = async () => {
    await api.signOut();
    router.replace("/login");
  };

  // Bring the newest turn to the top of the view, so its headline is what you read first.
  const lastId = turns.at(-1)?.id;
  useEffect(() => {
    if (lastId) document.getElementById(`turn-${lastId}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [lastId, pending]);

  const ask = async (question: string) => {
    const q = question.trim();
    if (!q || pending) return;
    const id = crypto.randomUUID();
    const sid = sessionId();
    setTurns((t) => [...t, { id, question: q }]);
    setCurrentId(sid);
    // Show the conversation in the list at once; the server's list replaces it afterwards.
    setSessions((list) => {
      const now = new Date().toISOString();
      const old = list?.find((x) => x.session_id === sid);
      const entry = old
        ? { ...old, questions: old.questions + 1, updated_at: now }
        : { session_id: sid, title: q, questions: 1, started_at: now, updated_at: now };
      return [entry, ...(list ?? []).filter((x) => x.session_id !== sid)];
    });
    setDraft("");
    setPending(true);
    const r = await api.ask(q, sid);
    setPending(false);
    setTurns((t) => t.map((x) => (x.id === id ? (r.ok ? { ...x, result: r.data } : { ...x, error: r.code }) : x)));
    if (r.ok && r.data.route === "investigate") setScope(scopeChips(r.data.scope));
    if (!r.ok && r.code === "unauthorized") router.replace("/login");
    refreshBudget();
    refreshSessions();
    input.current?.focus();
  };

  /** Reopen a past conversation from the stored answers (no model call). */
  const openSession = async (sid: string) => {
    if (pending || sid === currentId) return;
    setCurrentId(sid);
    setOpening(true);
    const r = await api.session(sid);
    setOpening(false);
    if (!r.ok) {
      setTurns([{ id: crypto.randomUUID(), question: "Open conversation", error: r.code }]);
      return;
    }
    session.current = sid;
    setTurns(
      r.data.turns.map((t) => ({
        id: t.request_id,
        question: t.question,
        ...(t.response ? { result: t.response } : { error: t.status === "running" ? "not_finished" : (t.error ?? "internal_error") }),
      })),
    );
    const lastInvestigation = [...r.data.turns].reverse().find((t) => t.response?.route === "investigate");
    setScope(r.data.scope_active && lastInvestigation?.response ? scopeChips(lastInvestigation.response.scope) : null);
    setReopened({ expired: !r.data.scope_active && !!lastInvestigation });
    setDraft("");
  };

  const newAnalysis = () => {
    if (scope) api.clearScope(sessionId());
    setTurns([]);
    setScope(null);
    setCurrentId(null);
    setReopened(null);
    session.current = newSessionId();
    input.current?.focus();
  };

  const clearScope = async () => {
    await api.clearScope(sessionId());
    setScope(null);
  };

  const suggestions = catalog
    ? catalog.examples.slice(0, 3).map((e) => e.questions[0])
    : EXAMPLES.slice(0, 3).map((e) => e.title);

  return (
    <CatalogProvider value={catalog}>
    <div className="flex h-dvh overflow-hidden">
      <div className="hidden lg:flex">
        <Sidebar
          sessions={sessions}
          currentId={currentId}
          pendingId={pending ? currentId : null}
          loading={opening}
          onOpen={openSession}
          onNew={newAnalysis}
          budget={budget}
          health={health}
          user={user}
          onSignOut={signOut}
        />
      </div>

      <main className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center gap-3 border-b border-zinc-200 bg-white/80 px-5 backdrop-blur">
          <Logo className="size-6 lg:hidden" />
          <span className="text-sm font-medium text-zinc-900">Workspace</span>
          {scope && scope.length > 0 && (
            <div className="flex min-w-0 items-center gap-1.5" title="Follow-up questions inherit this scope">
              <span className="text-xs text-zinc-400">·</span>
              <span className="hidden text-xs text-zinc-500 sm:inline">Session scope</span>
              {scope.map((s) => (
                <span key={s} className="truncate rounded-md bg-brand-50 px-2 py-0.5 text-xs font-medium text-brand-700 ring-1 ring-brand-100 ring-inset">
                  {s}
                </span>
              ))}
              <button type="button" aria-label="Clear scope" onClick={clearScope} className="rounded p-0.5 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-700">
                <X className="size-3.5" />
              </button>
            </div>
          )}
          <div className="ml-auto flex items-center gap-2">
            {user && (
              <Button size="sm" variant="ghost" onClick={openGuide}>
                <BookOpen className="size-3.5" /> Data guide
              </Button>
            )}
            <Button size="sm" className="lg:hidden" onClick={newAnalysis}>New</Button>
          </div>
        </header>

        {user === null ? (
          <div className="flex flex-1 items-center justify-center text-sm text-zinc-500">
            <Loader2 className="mr-2 size-4 animate-spin" /> Connecting…
          </div>
        ) : (
          <>
            <div className="scroll-thin flex-1 overflow-y-auto">
              {opening ? (
                <div className="flex h-full items-center justify-center text-sm text-zinc-500">
                  <Loader2 className="mr-2 size-4 animate-spin" /> Opening conversation…
                </div>
              ) : turns.length === 0 ? (
                <EmptyState onPick={ask} onOpenGuide={openGuide} />
              ) : (
                <div className="mx-auto w-full max-w-4xl space-y-8 px-6 py-8">
                  {reopened && (
                    <Callout tone="info" icon={<History className="size-4" />}>
                      Reopened from history: these answers are the saved ones, so nothing was re-run.
                      {reopened.expired
                        ? " The investigation scope of this conversation has expired, so new follow-up questions start without it."
                        : " New questions continue this conversation."}
                    </Callout>
                  )}
                  {turns.map((t) => (
                    <section key={t.id} id={`turn-${t.id}`} className="scroll-mt-6 space-y-3">
                      <div className="flex justify-end">
                        <p className="max-w-[80%] rounded-2xl rounded-br-md bg-zinc-900 px-4 py-2.5 text-sm text-white [overflow-wrap:anywhere]">{t.question}</p>
                      </div>
                      {t.result ? (
                        <AnswerCard result={t.result} onFollowup={ask} onTrace={setTraceId} onOpenGuide={openGuide} suggestions={suggestions} />
                      ) : t.error ? (
                        <Callout tone="error">{errorMessage(t.error)}</Callout>
                      ) : (
                        <PendingCard />
                      )}
                    </section>
                  ))}
                  <div className="h-[40vh]" aria-hidden="true" />
                </div>
              )}
            </div>

            <div className="shrink-0 bg-gradient-to-t from-[#f7f7f8] via-[#f7f7f8] to-transparent px-6 pt-2 pb-5">
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  ask(draft);
                }}
                className="mx-auto flex max-w-4xl items-end gap-2 rounded-2xl border border-zinc-200 bg-white p-2 pl-4 shadow-lg shadow-zinc-200/50 focus-within:border-brand-500/60 focus-within:ring-4 focus-within:ring-brand-100"
              >
                <label htmlFor="question" className="sr-only">Ask a question about the orders</label>
                <textarea
                  id="question"
                  ref={input}
                  rows={1}
                  maxLength={MAX_CHARS}
                  value={draft}
                  disabled={pending}
                  onChange={(e) => setDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      ask(draft);
                    }
                  }}
                  placeholder="Ask about revenue, delivery performance, sellers, reviews…"
                  className="max-h-40 min-h-[40px] flex-1 resize-none bg-transparent py-2.5 text-[15px] outline-none placeholder:text-zinc-400 disabled:opacity-60"
                />
                {draft.length > MAX_CHARS * 0.8 && (
                  <span className="pb-3 text-xs text-zinc-400 tabular-nums">{draft.length}/{MAX_CHARS}</span>
                )}
                <Button type="submit" variant="primary" aria-label="Ask" className="size-10 rounded-xl p-0" disabled={pending || !draft.trim()}>
                  {pending ? <Loader2 className="size-4 animate-spin" /> : <ArrowUp className="size-4" />}
                </Button>
              </form>
              <p className="mx-auto mt-2 max-w-4xl text-center text-[11px] text-zinc-400">
                Answers describe what the data shows, not why. Check the Evidence tab for the exact queries.
              </p>
            </div>
          </>
        )}
      </main>

      <DataGuide
        open={guideOpen}
        catalog={catalog}
        error={catalogError}
        onClose={() => setGuideOpen(false)}
        onAsk={(q) => {
          setGuideOpen(false);
          ask(q);
        }}
      />
      <TraceDrawer key={traceId ?? "none"} api={api} requestId={traceId} onClose={() => setTraceId(null)} />
    </div>
    </CatalogProvider>
  );
}
