-- 006: conversation history (GET /v1/sessions). The web app lists past conversations and
-- reopens them from the request rows the recorder already stores (question and response);
-- this index serves those lookups. No new data is stored.

CREATE INDEX requests_session_idx ON trace.requests (session_id, created_at)
    WHERE kind = 'request' AND session_id IS NOT NULL;
