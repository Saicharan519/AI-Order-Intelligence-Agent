"""Load the Olist CSVs into the typed raw.* tables (FR-19).

Properties:
  * Atomic: everything runs in one transaction. Any error (bad header, bad value,
    wrong row count) rolls back the whole load, leaving the previous data intact.
  * Idempotent: tables are truncated and reloaded, so repeated runs give identical results.
  * Explicit typing: rows are streamed as text into a temporary staging table with COPY,
    then cast into the typed table. Empty strings become NULL. A malformed value fails
    with PostgreSQL's message naming the type and the value.
  * Verified: header names must match the table columns, and row counts must match
    the expected source counts before the transaction commits.

The CSVs are parsed with Python's csv module because the source mixes quoted and
unquoted fields, has line breaks inside quoted review comments, and one file has a
byte-order mark and Windows line endings.

Usage:
    python scripts/load_data.py [--data-dir PATH]
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

import psycopg
from psycopg import sql

from orderintel.config import get_settings
from orderintel.db.connect import connect_owner

SOURCES: dict[str, str] = {
    "orders": "olist_orders_dataset.csv",
    "order_items": "olist_order_items_dataset.csv",
    "order_payments": "olist_order_payments_dataset.csv",
    "order_reviews": "olist_order_reviews_dataset.csv",
    "customers": "olist_customers_dataset.csv",
    "products": "olist_products_dataset.csv",
    "sellers": "olist_sellers_dataset.csv",
    "product_category_name_translation": "product_category_name_translation.csv",
}

EXPECTED_ROWS: dict[str, int] = {
    "orders": 99_441,
    "order_items": 112_650,
    "order_payments": 103_886,
    "order_reviews": 99_224,
    "customers": 99_441,
    "products": 32_951,
    "sellers": 3_095,
    "product_category_name_translation": 71,
}


class LoadError(Exception):
    pass


def table_columns(conn: psycopg.Connection, table: str) -> list[tuple[str, str]]:
    """(name, SQL type) of the loadable columns, in order; identity columns excluded."""
    return conn.execute(
        """
        SELECT a.attname, format_type(a.atttypid, a.atttypmod)
        FROM pg_attribute a
        WHERE a.attrelid = %s::regclass AND a.attnum > 0
          AND NOT a.attisdropped AND a.attidentity = ''
        ORDER BY a.attnum
        """,
        (f"raw.{table}",),
    ).fetchall()


def load_table(conn: psycopg.Connection, table: str, path: Path) -> None:
    cols = table_columns(conn, table)
    names = [c for c, _ in cols]
    stage = sql.Identifier(f"stage_{table}")
    col_ids = sql.SQL(", ").join(map(sql.Identifier, names))

    conn.execute(
        sql.SQL("CREATE TEMP TABLE {} ({}) ON COMMIT DROP").format(
            stage, sql.SQL(", ").join(sql.SQL("{} text").format(sql.Identifier(c)) for c in names)
        )
    )

    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        if header != names:
            raise LoadError(f"{path.name}: header {header} does not match raw.{table} {names}")
        with conn.cursor().copy(sql.SQL("COPY {} ({}) FROM STDIN").format(stage, col_ids)) as cp:
            for row in reader:
                if len(row) != len(names):
                    raise LoadError(
                        f"{path.name} line {reader.line_num}: "
                        f"{len(row)} fields, expected {len(names)}"
                    )
                cp.write_row(row)

    casts = sql.SQL(", ").join(
        sql.SQL("NULLIF({}, '')::{}").format(sql.Identifier(c), sql.SQL(t)) for c, t in cols
    )
    try:
        conn.execute(
            sql.SQL("INSERT INTO {} ({}) SELECT {} FROM {}").format(
                sql.Identifier("raw", table), col_ids, casts, stage
            )
        )
    except psycopg.Error as e:
        raise LoadError(f"raw.{table}: {e.diag.message_primary}") from e


def load_all(
    data_dir: Path, settings=None, expected: dict[str, int] | None = None
) -> dict[str, int]:
    """Load every source file; `settings` and `expected` let the mini fixture reuse this."""
    expected = expected or EXPECTED_ROWS
    missing = [f for f in SOURCES.values() if not (data_dir / f).is_file()]
    if missing:
        raise LoadError(f"missing files in {data_dir}: {', '.join(missing)}")

    with connect_owner(settings) as conn, conn.transaction():
        conn.execute(
            sql.SQL("TRUNCATE {} RESTART IDENTITY").format(
                sql.SQL(", ").join(sql.Identifier("raw", t) for t in SOURCES)
            )
        )
        for table, filename in SOURCES.items():
            load_table(conn, table, data_dir / filename)

        counts = {
            t: conn.execute(
                sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier("raw", t))
            ).fetchone()[0]
            for t in SOURCES
        }
        wrong = {t: (n, expected[t]) for t, n in counts.items() if n != expected[t]}
        if wrong:
            detail = "; ".join(f"{t}: got {n:,}, expected {e:,}" for t, (n, e) in wrong.items())
            raise LoadError(f"row counts do not match, load rolled back: {detail}")
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Load Olist CSVs into raw.*")
    parser.add_argument("--data-dir", type=Path, default=get_settings().data_dir)
    args = parser.parse_args(argv)

    started = time.perf_counter()
    try:
        counts = load_all(args.data_dir)
    except LoadError as e:
        print(f"LOAD FAILED (no changes committed): {e}", file=sys.stderr)
        return 1
    for table, n in counts.items():
        print(f"  raw.{table:<36} {n:>9,}  ok")
    print(f"Loaded {sum(counts.values()):,} rows in {time.perf_counter() - started:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
