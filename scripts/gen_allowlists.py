"""Generate the validator's view/column allow-list by introspecting the database (T-4.1).

Reads what oi_agent can actually SELECT in schema analytics, with column types and the
database COMMENTs, and writes src/orderintel/guard/allowlist.json. The file is committed;
tests/integration/test_allowlist_drift.py fails if the database and the file diverge.

    python scripts/gen_allowlists.py [--check]
"""

from __future__ import annotations

import argparse
import json
import sys

from orderintel.db.connect import connect_agent
from orderintel.guard.allowlists import ALLOWLIST_FILE


def introspect() -> dict:
    with connect_agent() as conn:
        views = conn.execute(
            """
            SELECT c.relname, obj_description(c.oid, 'pg_class')
            FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'analytics' AND c.relkind = 'v'
              AND has_table_privilege(c.oid, 'SELECT')
            ORDER BY 1
            """
        ).fetchall()
        result = {}
        for view, comment in views:
            cols = conn.execute(
                """
                SELECT a.attname, format_type(a.atttypid, a.atttypmod),
                       col_description(a.attrelid, a.attnum)
                FROM pg_attribute a
                WHERE a.attrelid = ('analytics.' || quote_ident(%s))::regclass
                  AND a.attnum > 0 AND NOT a.attisdropped
                ORDER BY a.attnum
                """,
                (view,),
            ).fetchall()
            result[view] = {
                "comment": comment or "",
                "columns": {name: {"type": typ, "comment": c or ""} for name, typ, c in cols},
            }
    return {"schema": "analytics", "views": result}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail if the file is out of date")
    args = parser.parse_args(argv)
    data = introspect()
    text = json.dumps(data, indent=2, sort_keys=True) + "\n"
    if args.check:
        current = ALLOWLIST_FILE.read_text(encoding="utf-8") if ALLOWLIST_FILE.exists() else ""
        if current != text:
            print("allowlist.json is out of date: run scripts/gen_allowlists.py")
            return 1
        print("allowlist.json matches the database")
        return 0
    ALLOWLIST_FILE.write_text(text, encoding="utf-8", newline="\n")
    n_cols = sum(len(v["columns"]) for v in data["views"].values())
    print(f"wrote {ALLOWLIST_FILE.name}: {len(data['views'])} views, {n_cols} columns")
    return 0


if __name__ == "__main__":
    sys.exit(main())
