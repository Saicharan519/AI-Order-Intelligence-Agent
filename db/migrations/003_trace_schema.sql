-- 003: request tracing and spend ledger (technical design, section 6.5).
-- Written by oi_trace, which cannot read business data. The recorder is wired in M9;
-- the LLM budget guard (M5) reads trace.spend.

CREATE SCHEMA trace;

CREATE TABLE trace.requests (
    id               uuid PRIMARY KEY,
    created_at       timestamptz NOT NULL DEFAULT now(),
    session_id       text,
    config_name      text NOT NULL,          -- e.g. prod, eval:C, calibration
    model            text,
    question         text,
    route            text,
    status           text NOT NULL,
    latency_ms       integer,
    tokens_in        integer NOT NULL DEFAULT 0,
    tokens_cache_hit integer NOT NULL DEFAULT 0,
    tokens_out       integer NOT NULL DEFAULT 0,
    cost_usd         numeric(12,6) NOT NULL DEFAULT 0 CHECK (cost_usd >= 0),
    scope            jsonb,
    response         jsonb,
    error            text
);
CREATE INDEX requests_created_at_idx ON trace.requests (created_at);

CREATE TABLE trace.steps (
    request_id uuid NOT NULL REFERENCES trace.requests (id) ON DELETE CASCADE,
    step_no    integer NOT NULL,
    kind       text NOT NULL CHECK (kind IN ('llm', 'validator', 'sql', 'playbook', 'grounding', 'lint')),
    payload    jsonb,                         -- never secrets
    ms         integer,
    PRIMARY KEY (request_id, step_no)
);

-- Total and per-day (UTC) spend, used by the budget guard.
CREATE VIEW trace.spend AS
SELECT
    coalesce(sum(cost_usd), 0)                                                    AS total_usd,
    coalesce(sum(cost_usd) FILTER (
        WHERE created_at >= date_trunc('day', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'), 0)
                                                                                  AS today_usd,
    count(*)                                                                      AS requests
FROM trace.requests;

GRANT USAGE ON SCHEMA trace TO oi_trace;
GRANT SELECT, INSERT, UPDATE ON trace.requests, trace.steps TO oi_trace;
GRANT SELECT ON trace.spend TO oi_trace;
