"use client";

import { Check, Copy } from "lucide-react";
import { useState } from "react";

const KEYWORDS = new Set(
  (
    "select from where group by order having limit with as join left right inner outer full on and or not " +
    "in is null case when then else end distinct count sum avg min max round cast filter over partition " +
    "between like ilike asc desc union all nullif coalesce extract date interval true false"
  ).split(" "),
);

// Tokens: strings, numbers, words, everything else. Rendered as spans, never as HTML.
const TOKEN = /('(?:[^']|'')*')|(\b\d+(?:\.\d+)?\b)|([A-Za-z_][A-Za-z0-9_]*)|(\s+|[^\sA-Za-z0-9_']+)/g;

/** Break a long one-line query before its main clauses, for reading. */
export function prettySql(sql: string): string {
  return sql
    .replace(/\s+(FROM|WHERE|GROUP BY|ORDER BY|HAVING|LIMIT|LEFT JOIN|JOIN|UNION ALL)\s+/g, "\n$1 ")
    .replace(/\)\s+SELECT\s+/g, ")\nSELECT ");
}

export function SqlBlock({ sql }: { sql: string }) {
  const [copied, setCopied] = useState(false);
  const text = prettySql(sql);
  const parts: React.ReactNode[] = [];
  let i = 0;
  for (const m of text.matchAll(TOKEN)) {
    const [tok, str, num, word] = m;
    const cls = str ? "sql-str" : num ? "sql-num" : word && KEYWORDS.has(word.toLowerCase()) ? "sql-kw" : undefined;
    parts.push(cls ? <span key={i++} className={cls}>{tok}</span> : tok);
  }
  return (
    <div className="group relative">
      <pre className="scroll-dark max-h-72 overflow-auto rounded-lg bg-zinc-950 p-3.5 font-mono text-[12.5px] leading-relaxed whitespace-pre-wrap text-zinc-200">
        {parts}
      </pre>
      <button
        type="button"
        aria-label="Copy SQL"
        onClick={async () => {
          await navigator.clipboard?.writeText(sql);
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        }}
        className="absolute top-2 right-2 rounded-md bg-zinc-800 p-1.5 text-zinc-300 opacity-0 transition group-hover:opacity-100 hover:text-white focus:opacity-100"
      >
        {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
      </button>
    </div>
  );
}
