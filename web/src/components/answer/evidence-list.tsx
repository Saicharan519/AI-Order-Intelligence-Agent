"use client";

import { Clock, Database, ShieldCheck, ShieldX } from "lucide-react";
import { plural } from "@/lib/format";
import type { Evidence } from "@/lib/types";
import { Badge, Disclosure } from "../ui";
import { DataTable } from "./data-table";
import { SqlBlock } from "./sql-block";

const STAGE_LABELS: Record<string, string> = {
  rejected: "SQL validator",
  rule: "revenue rule",
  exec_error: "database",
  parse_error: "reply parser",
};

export function EvidenceList({ evidence, columns }: { evidence: Evidence[]; columns?: string[] }) {
  if (!evidence.length) return <p className="text-sm text-zinc-500">No query was run for this answer.</p>;
  return (
    <ol className="space-y-4">
      {evidence.map((e, i) => {
        const v = e.validator;
        const retries = e.attempts.filter((a) => a.stage && a.stage !== "ok");
        const params = Object.entries(e.params ?? {});
        return (
          <li key={e.id} className="rounded-lg border border-zinc-200 p-4">
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <span className="flex size-6 items-center justify-center rounded-md bg-zinc-900 text-xs font-semibold text-white">
                {i + 1}
              </span>
              <span className="text-sm font-medium text-zinc-900">
                {e.kind === "playbook_step" ? `Playbook step · ${e.id}` : `Query ${e.id}`}
              </span>
              {v &&
                (v.ok ? (
                  <Badge tone="good" icon={<ShieldCheck className="size-3" />}>
                    Validated · {v.rules_checked.length} rules
                  </Badge>
                ) : (
                  <Badge tone="bad" icon={<ShieldX className="size-3" />}>
                    Not validated
                  </Badge>
                ))}
              <Badge icon={<Database className="size-3" />}>{plural(e.row_count, "row")}</Badge>
              {e.ms > 0 && <Badge icon={<Clock className="size-3" />}>{e.ms} ms</Badge>}
            </div>
            {e.sql && <SqlBlock sql={e.sql} />}
            {params.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {params.map(([k, val]) => (
                  <code key={k} className="rounded bg-zinc-100 px-1.5 py-0.5 font-mono text-[11px] text-zinc-700">
                    {k} = {JSON.stringify(val)}
                  </code>
                ))}
              </div>
            )}
            {retries.length > 0 && (
              <div className="mt-3 space-y-1">
                {retries.map((a, n) => (
                  <p key={n} className="text-xs text-amber-700">
                    Attempt rejected by the <b>{STAGE_LABELS[a.stage ?? ""] ?? a.stage}</b>: {a.feedback}
                  </p>
                ))}
              </div>
            )}
            {e.rows_preview.length > 0 && (
              <div className="mt-3">
                <Disclosure title={`Preview of the first ${plural(e.rows_preview.length, "row")}`}>
                  <DataTable
                    columns={
                      columns && evidence.length === 1 && columns.length === e.rows_preview[0].length
                        ? columns
                        : e.rows_preview[0].map((_, c) => `column_${c + 1}`)
                    }
                    rows={e.rows_preview}
                    download={false}
                  />
                </Disclosure>
              </div>
            )}
          </li>
        );
      })}
    </ol>
  );
}
