-- 009: forget a user's conversations when an admin deletes the account.
--
-- trace.requests is also the spend ledger (trace.spend sums its llm_call rows), and oi_trace
-- is deliberately not allowed to DELETE from it. So this function, owned by the owner and run
-- with the owner's rights, does exactly two things and nothing else:
--   1. on the model-call rows of the user's questions: erases the text (question, response,
--      error, session) but keeps cost, tokens, model and time, so the money spent still counts
--      toward the budget caps;
--   2. deletes the user's own question rows (kind 'request'; their steps go with them).
-- oi_trace may call it; it still cannot delete ledger rows itself.

CREATE FUNCTION trace.forget_user(target uuid) RETURNS integer
    LANGUAGE plpgsql
    SECURITY DEFINER
    SET search_path = pg_catalog, trace
AS $$
DECLARE
    removed integer;
BEGIN
    IF target IS NULL THEN
        RAISE EXCEPTION 'forget_user needs a user id';
    END IF;
    UPDATE trace.requests c
       SET question = NULL, response = NULL, error = NULL, session_id = NULL
      FROM trace.requests r
     WHERE c.parent_id = r.id AND c.kind = 'llm_call'
       AND r.kind = 'request' AND r.user_id = target;
    DELETE FROM trace.requests WHERE kind = 'request' AND user_id = target;
    GET DIAGNOSTICS removed = ROW_COUNT;
    RETURN removed;
END;
$$;

REVOKE ALL ON FUNCTION trace.forget_user(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION trace.forget_user(uuid) TO oi_trace;
