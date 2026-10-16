-- 004: injection-test data (technical design, sections 6.3 and 7.5). Test-only.
-- Synthetic review-style text, some of it poisoned with instructions and canary strings,
-- written by the injection suite (oi_owner) before each run. Read only by oi_injtest through
-- the view, via the test-only get_review_text tool. oi_agent has no access: the product
-- never sees review text.

CREATE SCHEMA injtest;

CREATE TABLE injtest.review_rows (
    order_id    text PRIMARY KEY,
    review_text text NOT NULL,
    case_id     text             -- the attack case that wrote the row; NULL for benign rows
);

CREATE VIEW injtest.reviews_with_text AS
SELECT order_id, review_text FROM injtest.review_rows;

REVOKE ALL ON SCHEMA injtest FROM PUBLIC;
GRANT USAGE ON SCHEMA injtest TO oi_injtest;
GRANT SELECT ON injtest.reviews_with_text TO oi_injtest;
