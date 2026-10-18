import { describe, expect, it } from "vitest";
import {
  chartMeasures,
  isPartialRow,
  errorMessage,
  formatCell,
  formatMonth,
  humanize,
  newSessionId,
  plural,
  reportMetrics,
  scopeChips,
  scopeLines,
  stageRows,
  tableRecords,
  toCsv,
  toNumber,
  usageParts,
} from "@/lib/format";
import type { AskResponse } from "@/lib/types";
import { groupByDate } from "@/components/sidebar";
import investigation from "./fixtures/investigation.json";
import trend from "./fixtures/late_trend.json";

describe("format helpers", () => {
  it("turns numeric strings back into numbers and leaves other strings alone", () => {
    expect(toNumber("497970.94")).toBe(497970.94);
    expect(toNumber("12")).toBe(12);
    expect(toNumber("-1.5")).toBe(-1.5);
    expect(toNumber("2017-01-01")).toBe("2017-01-01");
    expect(toNumber("955fee9216a65b617aa5c0531780ce60")).toBe("955fee9216a65b617aa5c0531780ce60");
    expect(toNumber("")).toBe("");
    expect(toNumber(null)).toBe(null);
  });

  it("builds records from columns and rows", () => {
    expect(tableRecords(["category", "revenue"], [["toys", "10.50"]])).toEqual([{ category: "toys", revenue: 10.5 }]);
  });

  it("humanizes column names", () => {
    expect(humanize("late_rate_pct")).toBe("Late rate %");
    expect(humanize("seller_id")).toBe("Seller ID");
    expect(humanize("month")).toBe("Month");
  });

  it("formats money, rates, counts and missing values", () => {
    expect(formatCell("revenue", 497970.94)).toBe("R$497,970.94");
    expect(formatCell("late_rate_pct", 2.93)).toBe("2.93%");
    expect(formatCell("orders_count", 1105)).toBe("1,105");
    expect(formatCell("is_partial", false)).toBe("No");
    expect(formatCell("x", null)).toBe("—");
  });

  it("formats months and plurals", () => {
    expect(formatMonth("2018-03-01")).toBe("Mar 2018");
    expect(formatMonth("2018-03")).toBe("Mar 2018");
    expect(formatMonth("RJ")).toBe("RJ");
    expect(plural(1, "row")).toBe("1 row");
    expect(plural(2000, "row")).toBe("2,000 rows");
  });

  it("maps every known error code and falls back for unknown ones", () => {
    expect(errorMessage("unauthorized")).toMatch(/access code/);
    expect(errorMessage("budget_exhausted")).toMatch(/No call was made/);
    expect(errorMessage("something_new")).toBe(errorMessage("internal_error"));
    expect(errorMessage(undefined)).toBe(errorMessage("internal_error"));
  });

  it("states the scope of a recorded answer", () => {
    const r = trend as unknown as AskResponse;
    const lines = scopeLines(r.scope);
    expect(lines[0]).toEqual({ label: "Period", text: "2017-01-01 to 2018-08-01" });
    expect(lines.filter((l) => l.label === "Definition")).toHaveLength(3);
    expect(lines.at(-1)).toEqual({ label: "Rows", text: "20" });
    expect(scopeChips(r.scope)).toEqual(["Period: 2017-01-01 to 2018-08-01"]);
  });

  it("summarises usage", () => {
    const parts = usageParts((trend as unknown as AskResponse).usage);
    expect(parts[0]).toBe("3 model calls (3 cached)");
    expect(parts[2]).toBe("$0.00000");
  });

  it("reads the investigation findings into metrics and stages", () => {
    const comp = (investigation as unknown as AskResponse).components[0];
    if (comp.type !== "report") throw new Error("expected a report");
    const m = reportMetrics(comp.findings);
    expect(m[0]).toEqual({ label: "Late rate", value: "19%", delta: "+13.2 pts vs 5.8% baseline", worse: true });
    expect(m.map((x) => x.label)).toEqual(["Late rate", "Late orders", "Delivered orders"]);
    expect(stageRows(comp.findings).find((s) => s.stage === "Carrier transit")).toEqual({
      stage: "Carrier transit",
      period: 12.97,
      baseline: 9.06,
    });
  });

  it("writes RFC 4180 CSV", () => {
    expect(toCsv(["a", "b"], [["x,y", 'say "hi"'], [null, 1]])).toBe('a,b\r\n"x,y","say ""hi"""\r\n,1');
  });

  it("makes session ids the API accepts", () => {
    expect(newSessionId()).toMatch(/^[A-Za-z0-9_-]{1,64}$/);
  });
});

describe("groupByDate", () => {
  it("groups conversations as Today, Yesterday, Previous 7 days and Older", () => {
    const now = new Date(2026, 9, 17, 12, 0);
    const at = (daysAgo: number) => new Date(2026, 9, 17 - daysAgo, 9, 0).toISOString();
    const item = (id: string, daysAgo: number) => ({ session_id: id, title: id, questions: 1, started_at: at(daysAgo), updated_at: at(daysAgo) });
    const groups = groupByDate([item("a", 0), item("b", 1), item("c", 5), item("d", 30)], now);
    expect(groups.map(([g, items]) => [g, items.map((i) => i.session_id)])).toEqual([
      ["Today", ["a"]],
      ["Yesterday", ["b"]],
      ["Previous 7 days", ["c"]],
      ["Older", ["d"]],
    ]);
  });
});

describe("chart helpers", () => {
  it("never mixes money and counts on one axis", () => {
    expect(chartMeasures(["orders_count", "revenue", "orders_with_items"])).toEqual(["revenue"]);
    expect(chartMeasures(["delivered_orders", "late_orders", "late_rate_pct"])).toEqual(["late_rate_pct"]);
    expect(chartMeasures(["orders", "customers"])).toEqual(["orders", "customers"]);
  });

  it("marks partial months by flag or by the catalog's list", () => {
    const partial = new Set(["2016-10"]);
    expect(isPartialRow({ month: "2016-10-01" }, "month", partial)).toBe(true);
    expect(isPartialRow({ month: "2017-10-01" }, "month", partial)).toBe(false);
    expect(isPartialRow({ period: "Sep 2016", partial_month: true }, "period", partial)).toBe(true);
    expect(isPartialRow({ month: "2017-01-01", is_partial: true }, "month", partial)).toBe(true);
  });
});
