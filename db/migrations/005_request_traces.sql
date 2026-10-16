-- 005: request-level traces (technical design, section 11; FR-15).
-- Until now every trace.requests row was one LLM call (the budget ledger). A user request
-- now gets its own row (kind = 'request', zero cost, the final response in `response`),
-- and the LLM calls it made point to it through parent_id. Existing rows keep
-- kind = 'llm_call'. trace.spend counts LLM calls only, so the budget totals are unchanged.

ALTER TABLE trace.requests
    ADD COLUMN kind text NOT NULL DEFAULT 'llm_call' CHECK (kind IN ('llm_call', 'request')),
    ADD COLUMN parent_id uuid REFERENCES trace.requests (id) ON DELETE SET NULL;
CREATE INDEX requests_parent_idx ON trace.requests (parent_id);

ALTER TABLE trace.requests
    ADD CONSTRAINT request_rows_cost_nothing CHECK (kind = 'llm_call' OR cost_usd = 0);

CREATE OR REPLACE VIEW trace.spend AS
SELECT
    coalesce(sum(cost_usd), 0)                                                    AS total_usd,
    coalesce(sum(cost_usd) FILTER (
        WHERE created_at >= date_trunc('day', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'), 0)
                                                                                  AS today_usd,
    count(*)                                                                      AS requests
FROM trace.requests
WHERE kind = 'llm_call';
