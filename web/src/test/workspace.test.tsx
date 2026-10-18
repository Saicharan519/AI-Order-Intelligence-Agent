// The screens, rendered against a fake API with recorded responses (no network, $0).
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { Api, ApiResult } from "@/lib/api";
import type { AskResponse, Budget, Catalog, SessionSummary, SessionTurn } from "@/lib/types";
import catalog from "./fixtures/catalog.json";
import { Workspace } from "@/components/workspace";
import investigation from "./fixtures/investigation.json";
import refused from "./fixtures/refused.json";
import about from "./fixtures/about.json";
import outOfRange from "./fixtures/out_of_range.json";
import partialMonth from "./fixtures/partial_month.json";
import sellerLookup from "./fixtures/seller_lookup.json";
import topCategories from "./fixtures/top_categories.json";

const BUDGET: Budget = {
  total_usd: 0.0789,
  today_usd: 0,
  total_cap_usd: 1.9,
  daily_cap_usd: 0.4,
  remaining_total_usd: 1.8211,
  remaining_today_usd: 0.4,
  llm_enabled: true,
};
const GOOD = "letmein";

type Stored = { session_id: string; turns: SessionTurn[] };

/** A fake API that keeps conversations in memory like the real one keeps them in traces. */
function fakeApi(
  opts: {
    local?: boolean;
    answers?: Record<string, ApiResult<AskResponse>>;
    history?: Stored[];
    scopeActive?: boolean;
  } = {},
) {
  const ok = <T,>(data: T): ApiResult<T> => ({ ok: true, data });
  const denied = { ok: false as const, code: "unauthorized", status: 401 };
  const store: Stored[] = [...(opts.history ?? [])];
  let clock = Date.now();
  const allowed = (code: string) => opts.local || code === GOOD;
  const record = (sid: string, question: string, r: ApiResult<AskResponse>) => {
    let c = store.find((x) => x.session_id === sid);
    if (!c) store.push((c = { session_id: sid, turns: [] }));
    c.turns.push({
      request_id: r.ok ? r.data.request_id : crypto.randomUUID(),
      created_at: new Date((clock += 1000)).toISOString(),
      question,
      status: r.ok ? r.data.status : "error",
      response: r.ok ? r.data : null,
      error: r.ok ? null : r.code,
    });
  };
  const api: Api = {
    config: vi.fn(async () => ok({ local: !!opts.local })),
    health: vi.fn(async () => ok({ status: "ok", database: "ok" as const, llm_enabled: true })),
    budget: vi.fn(async (code: string) => (opts.local || code === GOOD ? ok(BUDGET) : denied)),
    ask: vi.fn(async (code: string, question: string, sid: string) => {
      if (!allowed(code)) return denied;
      const r = opts.answers?.[question] ?? ok(topCategories as unknown as AskResponse);
      if (r.ok || r.code !== "unauthorized") record(sid, question, r);
      return r;
    }),
    trace: vi.fn(async () => ({ ok: false as const, code: "not_found", status: 404 })),
    clearScope: vi.fn(async () => ok({ cleared: true })),
    sessions: vi.fn(async (code: string) => {
      if (!allowed(code)) return denied;
      const list: SessionSummary[] = store
        .map((c) => ({
          session_id: c.session_id,
          title: c.turns[0].question,
          questions: c.turns.length,
          started_at: c.turns[0].created_at,
          updated_at: c.turns.at(-1)!.created_at,
        }))
        .sort((a, b) => b.updated_at.localeCompare(a.updated_at));
      return ok({ sessions: list });
    }),
    session: vi.fn(async (code: string, sid: string) => {
      if (!allowed(code)) return denied;
      const c = store.find((x) => x.session_id === sid);
      if (!c) return { ok: false as const, code: "not_found", status: 404 };
      return ok({ session_id: sid, scope_active: !!opts.scopeActive, turns: c.turns });
    }),
    catalog: vi.fn(async (code: string) => (allowed(code) ? ok(catalog as unknown as Catalog) : denied)),
  };
  return api;
}

async function unlock(user: ReturnType<typeof userEvent.setup>) {
  await user.type(await screen.findByLabelText("Access code"), GOOD);
  await user.click(screen.getByRole("button", { name: /unlock workspace/i }));
  await screen.findByText(/what do you want to know/i);
}

async function askQuestion(user: ReturnType<typeof userEvent.setup>, q: string) {
  await user.type(screen.getByLabelText("Ask a question about the orders"), `${q}{Enter}`);
}

describe("Workspace", () => {
  it("asks for the access code and explains what it is", async () => {
    render(<Workspace api={fakeApi()} />);
    expect(await screen.findByText("Enter your access code")).toBeInTheDocument();
    expect(screen.getByText("ACCESS_CODE")).toBeInTheDocument();
    expect(screen.getByLabelText("Access code")).toHaveAttribute("type", "password");
  });

  it("rejects a wrong code with a plain message", async () => {
    const user = userEvent.setup();
    render(<Workspace api={fakeApi()} />);
    await user.type(await screen.findByLabelText("Access code"), "wrong");
    await user.click(screen.getByRole("button", { name: /unlock workspace/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The access code is missing or wrong.");
  });

  it("skips the code screen in local mode", async () => {
    render(<Workspace api={fakeApi({ local: true })} />);
    expect(await screen.findByText(/what do you want to know/i)).toBeInTheDocument();
    expect(screen.queryByLabelText("Access code")).not.toBeInTheDocument();
    expect(await screen.findByText("$0.0789 / $1.90")).toBeInTheDocument();
  });

  it("answers a question with a headline, a chart, a table and evidence", async () => {
    const user = userEvent.setup();
    const api = fakeApi();
    render(<Workspace api={api} />);
    await unlock(user);
    await askQuestion(user, "Top 5 categories by revenue in 2017");

    expect(await screen.findByText(/bed_bath_table led 2017 category revenue/)).toBeInTheDocument();
    expect(api.ask).toHaveBeenCalledWith(GOOD, "Top 5 categories by revenue in 2017", expect.stringMatching(/^[A-Za-z0-9]{16}$/));
    expect(screen.getByRole("img", { name: /bar chart of Revenue by Category/ })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "R$497,970.94" })).toBeInTheDocument();
    expect(screen.getByText("9 numbers traced to data")).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: /Evidence/ }));
    expect(screen.getByText(/Validated · 9 rules/)).toBeInTheDocument();
    expect(screen.getByText(/Query e1/)).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: /Scope/ }));
    expect(screen.getByText("Period")).toBeInTheDocument();
  });

  it("starts from an example card", async () => {
    const user = userEvent.setup();
    const api = fakeApi();
    render(<Workspace api={api} />);
    await unlock(user);
    await user.click(screen.getByRole("button", { name: /How is the late-delivery rate trending/ }));
    expect(api.ask).toHaveBeenCalledWith(GOOD, "How is the late-delivery rate trending?", expect.any(String));
  });

  it("shows an investigation report, sets the session scope, and clears it", async () => {
    const user = userEvent.setup();
    const q = "Why was March 2018 so bad for deliveries?";
    const api = fakeApi({ answers: { [q]: { ok: true, data: investigation as unknown as AskResponse } } });
    render(<Workspace api={api} />);
    await unlock(user);
    await askQuestion(user, q);

    expect(await screen.findByText("Verdict: Elevated")).toBeInTheDocument();
    expect(screen.getByText("Top driver: Carrier transit")).toBeInTheDocument();
    expect(screen.getByText("Where the days went")).toBeInTheDocument();
    expect(screen.getByText("States by excess late orders")).toBeInTheDocument();
    expect(screen.getByText("Period: 2018-03-01 to 2018-03-31")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Clear scope" }));
    expect(api.clearScope).toHaveBeenCalled();
    await waitFor(() => expect(screen.queryByText("Period: 2018-03-01 to 2018-03-31")).not.toBeInTheDocument());
  });

  it("asks a follow-up when its chip is clicked", async () => {
    const user = userEvent.setup();
    const q = "Why was March 2018 so bad for deliveries?";
    const api = fakeApi({ answers: { [q]: { ok: true, data: investigation as unknown as AskResponse } } });
    render(<Workspace api={api} />);
    await unlock(user);
    await askQuestion(user, q);
    await user.click(await screen.findByRole("button", { name: /Break down 2018-03 by product category/ }));
    expect(api.ask).toHaveBeenLastCalledWith(GOOD, "Break down 2018-03 by product category.", expect.any(String));
  });

  it("shows a long identifier in full in a compact tile, with caveats folded away", async () => {
    const user = userEvent.setup();
    const q = "what is the name of the seller";
    render(<Workspace api={fakeApi({ answers: { [q]: { ok: true, data: sellerLookup as unknown as AskResponse } } })} />);
    await unlock(user);
    await askQuestion(user, q);
    expect(await screen.findByTitle("955fee9216a65b617aa5c0531780ce60")).toHaveClass("font-mono");
    const toggle = screen.getByRole("button", { name: /Caveats \(8\)/ });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText(/2016-09 is a partial month/)).not.toBeInTheDocument();
    await user.click(toggle);
    expect(screen.getByText(/2016-09 is a partial month/)).toBeInTheDocument();
  });

  it("explains a refusal", async () => {
    const user = userEvent.setup();
    const q = "What will the weather be?";
    render(<Workspace api={fakeApi({ answers: { [q]: { ok: true, data: refused as unknown as AskResponse } } })} />);
    await unlock(user);
    await askQuestion(user, q);
    expect(await screen.findByText("Out of scope")).toBeInTheDocument();
    expect(screen.getByText("That's outside what I can answer")).toBeInTheDocument();
  });

  it("turns a refusal into a way forward: the reason, the guide, and questions to try", async () => {
    const user = userEvent.setup();
    const q = "Show me the dataset";
    const api = fakeApi({ answers: { [q]: { ok: true, data: refused as unknown as AskResponse } } });
    render(<Workspace api={api} />);
    await unlock(user);
    await askQuestion(user, q);
    expect(await screen.findByText(/The dataset covers Olist orders/)).toBeInTheDocument(); // the model's reason
    expect(screen.queryByText("I can't help with that request.")).not.toBeInTheDocument();

    const first = (catalog as unknown as Catalog).examples[0].questions[0];
    await user.click(screen.getByRole("button", { name: new RegExp(first) }));
    expect(api.ask).toHaveBeenLastCalledWith(GOOD, first, expect.any(String));

    await user.click(screen.getAllByRole("button", { name: /Explore the data/ })[0]);
    expect(await screen.findByRole("dialog", { name: "Explore the data" })).toBeInTheDocument();
  });

  it("turns API errors into plain messages", async () => {
    const user = userEvent.setup();
    const answers = {
      a: { ok: false as const, code: "budget_exhausted", status: 503 },
      b: { ok: false as const, code: "rate_limited", status: 429 },
    };
    render(<Workspace api={fakeApi({ answers })} />);
    await unlock(user);
    await askQuestion(user, "a");
    expect(await screen.findByText(/spending limit for the language model is reached/)).toBeInTheDocument();
    await askQuestion(user, "b");
    expect(await screen.findByText(/Too many questions in a short time/)).toBeInTheDocument();
  });

  it("returns to the code screen when the code stops working", async () => {
    const user = userEvent.setup();
    const answers = { x: { ok: false as const, code: "unauthorized", status: 401 } };
    render(<Workspace api={fakeApi({ answers })} />);
    await unlock(user);
    await askQuestion(user, "x");
    expect(await screen.findByText("Enter your access code")).toBeInTheDocument();
  });

  it("lists one conversation for several questions, and New analysis starts another", async () => {
    const user = userEvent.setup();
    render(<Workspace api={fakeApi()} />);
    await unlock(user);
    const nav = screen.getByRole("navigation", { name: "Conversations" });
    await askQuestion(user, "Top 5 categories by revenue in 2017");
    await screen.findByText(/bed_bath_table led 2017 category revenue/);
    await askQuestion(user, "What is the average order value for these categories?");
    await waitFor(() => expect(within(nav).getByText(/2 questions/)).toBeInTheDocument());
    expect(within(nav).getAllByRole("button")).toHaveLength(1); // one conversation, not one row per question
    expect(within(nav).getByText("Top 5 categories by revenue in 2017")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /New analysis/ }));
    expect(screen.getByText(/what do you want to know/i)).toBeInTheDocument();
    await askQuestion(user, "How many orders were late?");
    await waitFor(() => expect(within(nav).getAllByRole("button")).toHaveLength(2));
    const rows = within(nav).getAllByRole("button");
    expect(rows[0]).toHaveTextContent("How many orders were late?"); // newest first
    expect(rows[0]).toHaveAttribute("aria-current", "true");
  });

  it("shows saved conversations from earlier sessions and reopens one without asking again", async () => {
    const user = userEvent.setup();
    const r = topCategories as unknown as AskResponse;
    const earlier = new Date(Date.now() - 3 * 86_400_000).toISOString();
    const api = fakeApi({
      history: [
        {
          session_id: "old1",
          turns: [
            { request_id: r.request_id, created_at: earlier, question: "Top 5 categories by revenue in 2017", status: "ok", response: r, error: null },
            { request_id: "x2", created_at: earlier, question: "A question that failed", status: "error", response: null, error: "provider_error" },
          ],
        },
      ],
    });
    render(<Workspace api={api} />);
    await unlock(user);
    const nav = screen.getByRole("navigation", { name: "Conversations" });
    expect(await within(nav).findByText("Previous 7 days")).toBeInTheDocument();

    await user.click(within(nav).getByRole("button", { name: /Top 5 categories by revenue in 2017/ }));
    expect(await screen.findByText(/bed_bath_table led 2017 category revenue/)).toBeInTheDocument();
    expect(screen.getByText(/Reopened from history/)).toBeInTheDocument();
    expect(screen.getByText(/language model service is unavailable/)).toBeInTheDocument();
    expect(api.ask).not.toHaveBeenCalled(); // reopening costs nothing

    await askQuestion(user, "And in 2018?");
    expect(api.ask).toHaveBeenLastCalledWith(GOOD, "And in 2018?", "old1"); // continues the same conversation
  });

  it("says when a reopened investigation's scope has expired", async () => {
    const user = userEvent.setup();
    const inv = investigation as unknown as AskResponse;
    const turn = { request_id: inv.request_id, created_at: new Date().toISOString(), question: "Why was March 2018 so bad?", status: "ok", response: inv, error: null };
    render(<Workspace api={fakeApi({ history: [{ session_id: "inv1", turns: [turn] }] })} />);
    await unlock(user);
    await user.click(await within(screen.getByRole("navigation", { name: "Conversations" })).findByRole("button", { name: /Why was March 2018 so bad/ }));
    expect(await screen.findByText(/scope of this conversation has expired/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Clear scope" })).not.toBeInTheDocument();
  });

  it("restores the scope bar when the reopened investigation's scope is still active", async () => {
    const user = userEvent.setup();
    const inv = investigation as unknown as AskResponse;
    const turn = { request_id: inv.request_id, created_at: new Date().toISOString(), question: "Why was March 2018 so bad?", status: "ok", response: inv, error: null };
    render(<Workspace api={fakeApi({ history: [{ session_id: "inv2", turns: [turn] }], scopeActive: true })} />);
    await unlock(user);
    await user.click(await within(screen.getByRole("navigation", { name: "Conversations" })).findByRole("button", { name: /Why was March 2018 so bad/ }));
    expect(await screen.findByText("Period: 2018-03-01 to 2018-03-31")).toBeInTheDocument();
    expect(screen.getByText(/New questions continue this conversation/)).toBeInTheDocument();
  });
});

describe("Data guide", () => {
  it("opens from the header and shows counts from the catalog, not hard-coded text", async () => {
    const user = userEvent.setup();
    const api = fakeApi();
    render(<Workspace api={api} />);
    await unlock(user);
    await user.click(screen.getByRole("button", { name: /Data guide/ }));
    const guide = await screen.findByRole("dialog", { name: "Explore the data" });
    const f = (catalog as unknown as Catalog).facts;
    expect(within(guide).getByText(f.orders.toLocaleString("en-US"))).toBeInTheDocument();
    expect(within(guide).getByText(f.sellers.toLocaleString("en-US"))).toBeInTheDocument();
    expect(within(guide).getByText("What it cannot answer")).toBeInTheDocument();
    expect(api.ask).not.toHaveBeenCalled(); // opening the guide costs nothing
  });

  it("asks an example question and closes", async () => {
    const user = userEvent.setup();
    const api = fakeApi();
    render(<Workspace api={api} />);
    await unlock(user);
    await user.click(screen.getByRole("button", { name: /Not sure what to ask/ }));
    const guide = await screen.findByRole("dialog", { name: "Explore the data" });
    const delivery = (catalog as unknown as Catalog).examples.find((e) => e.topic === "Delivery")!;
    await user.click(within(guide).getByRole("button", { name: delivery.questions[1] }));
    expect(api.ask).toHaveBeenCalledWith(GOOD, delivery.questions[1], expect.any(String));
    expect(screen.queryByRole("dialog", { name: "Explore the data" })).not.toBeInTheDocument();
  });

  it("lists the tables with their columns and searches the definitions", async () => {
    const user = userEvent.setup();
    render(<Workspace api={fakeApi()} />);
    await unlock(user);
    await user.click(screen.getByRole("button", { name: /Data guide/ }));
    const guide = await screen.findByRole("dialog", { name: "Explore the data" });

    await user.click(within(guide).getByRole("tab", { name: /Tables/ }));
    expect(within(guide).getByText("is_late")).toBeInTheDocument(); // orders is open by default
    await user.click(within(guide).getByRole("button", { name: /^sellers/ }));
    expect(within(guide).getByText("seller_city")).toBeInTheDocument();

    await user.click(within(guide).getByRole("tab", { name: /Definitions/ }));
    await user.type(within(guide).getByPlaceholderText(/Search/), "freight");
    expect(within(guide).getByText("Freight")).toBeInTheDocument();
    expect(within(guide).queryByText("Repeat customer")).not.toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "Explore the data" })).not.toBeInTheDocument();
  });
});

describe("Answers built in code", () => {
  it("shows the dataset in the chat: counts, timeline, tables, sample orders and questions", async () => {
    const user = userEvent.setup();
    const q = "SHOW ME THE DATASET";
    const api = fakeApi({ answers: { [q]: { ok: true, data: about as unknown as AskResponse } } });
    render(<Workspace api={api} />);
    await unlock(user);
    await askQuestion(user, q);
    expect(await screen.findByText("About the data")).toBeInTheDocument();
    expect(screen.getByRole("figure", { name: "Orders per month across the data" })).toBeInTheDocument();
    expect(screen.getByText("Five example orders")).toBeInTheDocument();
    expect(screen.getAllByRole("row").length).toBeGreaterThanOrEqual(6); // header + 5 orders
    const first = (about as unknown as AskResponse).components.find((c) => c.type === "about") as unknown as {
      examples: { questions: string[] }[];
    };
    await user.click(screen.getByRole("button", { name: new RegExp(first.examples[0].questions[0]) }));
    expect(api.ask).toHaveBeenLastCalledWith(GOOD, first.examples[0].questions[0], expect.any(String));
    await user.click(screen.getByRole("button", { name: /Open the full data guide/ }));
    expect(await screen.findByRole("dialog", { name: "Explore the data" })).toBeInTheDocument();
  });

  it("charts a partial month next to a typical month and says it is partial", async () => {
    const user = userEvent.setup();
    const q = "why is the Revenue low in the october 2016?";
    render(<Workspace api={fakeApi({ answers: { [q]: { ok: true, data: partialMonth as unknown as AskResponse } } })} />);
    await unlock(user);
    await askQuestion(user, q);
    expect(await screen.findByText(/only partly covered by this data/)).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /bar chart of Orders by Period/ })).toBeInTheDocument();
    expect(screen.getByText(/Grey bars are partial months/)).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: /Typical month/ })).toBeInTheDocument();
  });

  it("says plainly when a period is outside the data", async () => {
    const user = userEvent.setup();
    const q = "Why was 2019 bad?";
    render(<Workspace api={fakeApi({ answers: { [q]: { ok: true, data: outOfRange as unknown as AskResponse } } })} />);
    await unlock(user);
    await askQuestion(user, q);
    expect(await screen.findByText(/There is no data for 2019/)).toBeInTheDocument();
    expect(screen.getByText("The data has nothing for that period or analysis.")).toBeInTheDocument();
  });

  it("guide explains the timeline and the fields that do not exist", async () => {
    const user = userEvent.setup();
    render(<Workspace api={fakeApi()} />);
    await unlock(user);
    await user.click(screen.getByRole("button", { name: /Data guide/ }));
    const guide = await screen.findByRole("dialog", { name: "Explore the data" });
    expect(within(guide).getByRole("figure", { name: "Orders per month across the data" })).toBeInTheDocument();
    expect(within(guide).getByText(/Trends and monthly comparisons use/)).toBeInTheDocument();
    expect(within(guide).getByText("product names")).toBeInTheDocument();
    expect(within(guide).getByText("product id, category, and weight")).toBeInTheDocument();
    await user.click(within(guide).getByRole("tab", { name: /Tables/ }));
    expect(within(guide).getByText(/Use this, not a per-order id, to count customers/)).toBeInTheDocument();
  });
});
