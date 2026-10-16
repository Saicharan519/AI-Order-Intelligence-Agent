"""Administrative trace queries (T-9.2; technical design 11): latency, cost per question,
validator rejection rate, and failure routes, over user requests (kind = 'request')."""

from __future__ import annotations

from orderintel.db.connect import connect_trace

SUMMARY_SQL = """
WITH req AS (
    SELECT r.id, r.route, r.status, r.latency_ms,
           (SELECT coalesce(sum(c.cost_usd), 0) FROM trace.requests c WHERE c.parent_id = r.id)
               AS cost_usd,
           EXISTS (SELECT 1 FROM trace.steps s WHERE s.request_id = r.id
                   AND s.kind = 'validator' AND s.payload->>'stage' = 'rejected') AS had_rejection
    FROM trace.requests r
    WHERE r.kind = 'request' AND r.created_at >= now() - make_interval(days => %s)
)
SELECT count(*)                                                        AS requests,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms)         AS p50_ms,
       percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms)        AS p95_ms,
       avg(cost_usd)                                                   AS cost_per_question,
       sum(cost_usd)                                                   AS cost_total,
       avg(had_rejection::int)                                         AS rejection_rate
FROM req
"""

ROUTES_SQL = """
SELECT coalesce(route, '-') AS route, status, count(*) AS n
FROM trace.requests
WHERE kind = 'request' AND created_at >= now() - make_interval(days => %s)
GROUP BY 1, 2 ORDER BY n DESC, 1, 2
"""


def summary(days: int = 30, settings=None) -> dict:
    with connect_trace(settings) as conn:
        cur = conn.execute(SUMMARY_SQL, (days,))
        cols = [d.name for d in cur.description]
        row = dict(zip(cols, cur.fetchone(), strict=True))
        routes = conn.execute(ROUTES_SQL, (days,)).fetchall()
    out = {k: (float(v) if v is not None and k != "requests" else v) for k, v in row.items()}
    out["routes"] = [{"route": r, "status": s, "n": n} for r, s, n in routes]
    return out
