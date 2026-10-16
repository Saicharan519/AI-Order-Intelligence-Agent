"""Administrative trace report (T-9.2): p50/p95 latency, cost per question, validator
rejection rate, and routes, over API requests in the last N days. Reads traces only.

Usage:
    python scripts/trace_report.py [--days 30]
"""

from __future__ import annotations

import argparse
import sys

from orderintel.trace.queries import summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--days", type=int, default=30)
    args = ap.parse_args(argv)
    s = summary(args.days)
    if not s["requests"]:
        print(f"No API requests in the last {args.days} days.")
        return 0
    print(f"API requests, last {args.days} days: {s['requests']}")
    print(f"  latency p50 {s['p50_ms'] / 1000:.1f} s, p95 {s['p95_ms'] / 1000:.1f} s")
    print(f"  cost per question ${s['cost_per_question']:.5f} (total ${s['cost_total']:.4f})")
    print(f"  requests with a validator rejection: {100 * s['rejection_rate']:.1f}%")
    for r in s["routes"]:
        print(f"  {r['route']:<12} {r['status']:<12} {r['n']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
