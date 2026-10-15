-- 002: the semantic layer (technical design, section 6.4; glossary/glossary.md).
-- These views are the product's data boundary: oi_agent can read them and nothing else.
-- Views run with their owner's (oi_owner's) privileges, so oi_agent needs no access to raw.*.
-- Each data trap found in M1 is neutralised here, once, instead of in every query.

CREATE SCHEMA analytics;

-- One row per reviewed order: the latest answered review. Review text is not exposed.
CREATE VIEW analytics.reviews AS
SELECT
    r.order_id,
    r.review_score,
    r.review_creation_date::date AS review_created_date,
    r.review_answer_timestamp    AS review_answer_ts,
    (coalesce(btrim(r.review_comment_message), '') <> ''
     OR coalesce(btrim(r.review_comment_title), '') <> '') AS has_comment
FROM (
    SELECT DISTINCT ON (order_id) *
    FROM raw.order_reviews
    ORDER BY order_id, review_answer_timestamp DESC, review_creation_date DESC, review_row_id DESC
) r;

-- One row per order with at least one payment: joining it to items cannot multiply rows.
CREATE VIEW analytics.payments AS
SELECT
    order_id,
    sum(payment_value)                                               AS payment_total,
    count(*)::int                                                    AS payment_count,
    max(payment_installments)::int                                   AS installments_max,
    string_agg(DISTINCT payment_type, '+' ORDER BY payment_type)     AS payment_types,
    (array_agg(payment_type ORDER BY payment_value DESC, payment_sequential))[1]
                                                                     AS primary_payment_type
FROM raw.order_payments
GROUP BY order_id;

CREATE VIEW analytics.sellers AS
SELECT seller_id, seller_city, seller_state
FROM raw.sellers;

-- One row per order.
CREATE VIEW analytics.orders AS
WITH items AS (
    SELECT order_id,
           count(*)::int                   AS item_count,
           count(DISTINCT seller_id)::int  AS seller_count,
           sum(price)                      AS items_revenue,
           sum(freight_value)              AS freight_total
    FROM raw.order_items
    GROUP BY order_id
)
SELECT
    o.order_id,
    c.customer_unique_id,
    c.customer_state,
    c.customer_city,
    o.order_status,
    o.order_purchase_timestamp                                   AS purchase_ts,
    o.order_purchase_timestamp::date                             AS purchase_date,
    date_trunc('month', o.order_purchase_timestamp)::date        AS purchase_month,
    o.order_approved_at                                          AS approved_ts,
    o.order_delivered_carrier_date                               AS carrier_ts,
    o.order_delivered_customer_date                              AS delivered_ts,
    o.order_estimated_delivery_date::date                        AS estimated_delivery_date,
    o.order_status NOT IN ('canceled', 'unavailable')            AS is_sale,
    d.is_delivered,
    CASE WHEN d.is_delivered
         THEN o.order_delivered_customer_date::date > o.order_estimated_delivery_date::date
    END                                                          AS is_late,
    CASE WHEN d.is_delivered
         THEN o.order_delivered_customer_date::date - o.order_estimated_delivery_date::date
    END                                                          AS days_late,
    CASE WHEN o.order_delivered_carrier_date >= o.order_purchase_timestamp
         THEN round(extract(epoch FROM o.order_delivered_carrier_date
                                      - o.order_purchase_timestamp) / 86400, 2)
    END                                                          AS seller_handling_days,
    CASE WHEN o.order_delivered_customer_date >= o.order_delivered_carrier_date
         THEN round(extract(epoch FROM o.order_delivered_customer_date
                                      - o.order_delivered_carrier_date) / 86400, 2)
    END                                                          AS carrier_transit_days,
    CASE WHEN o.order_estimated_delivery_date >= o.order_purchase_timestamp
         THEN round(extract(epoch FROM o.order_estimated_delivery_date
                                      - o.order_purchase_timestamp) / 86400, 2)
    END                                                          AS promised_days,
    CASE WHEN o.order_delivered_customer_date >= o.order_purchase_timestamp
         THEN round(extract(epoch FROM o.order_delivered_customer_date
                                      - o.order_purchase_timestamp) / 86400, 2)
    END                                                          AS delivery_days,
    coalesce(i.item_count, 0)                                    AS item_count,
    coalesce(i.seller_count, 0)                                  AS seller_count,
    coalesce(i.items_revenue, 0)                                 AS items_revenue,
    coalesce(i.freight_total, 0)                                 AS freight_total,
    p.payment_total,
    r.review_score,
    coalesce(r.has_comment, false)                               AS has_review_comment
FROM raw.orders o
JOIN raw.customers c ON c.customer_id = o.customer_id
CROSS JOIN LATERAL (
    SELECT o.order_status = 'delivered'
           AND o.order_delivered_customer_date IS NOT NULL AS is_delivered
) d
LEFT JOIN items i              ON i.order_id = o.order_id
LEFT JOIN analytics.payments p ON p.order_id = o.order_id
LEFT JOIN analytics.reviews r  ON r.order_id = o.order_id;

-- One row per order item, with order, customer and seller attributes denormalised so that
-- most item-level questions need no join.
CREATE VIEW analytics.order_items AS
SELECT
    i.order_id,
    i.order_item_id,
    i.product_id,
    i.seller_id,
    i.price,
    i.freight_value,
    CASE WHEN p.product_category_name IS NULL THEN 'unknown'
         ELSE coalesce(t.product_category_name_english, p.product_category_name)
    END                                                     AS category,
    p.product_weight_g,
    o.order_purchase_timestamp::date                        AS purchase_date,
    date_trunc('month', o.order_purchase_timestamp)::date   AS purchase_month,
    o.order_status,
    o.order_status NOT IN ('canceled', 'unavailable')       AS is_sale,
    CASE WHEN o.order_status = 'delivered' AND o.order_delivered_customer_date IS NOT NULL
         THEN o.order_delivered_customer_date::date > o.order_estimated_delivery_date::date
    END                                                     AS is_late,
    c.customer_unique_id,
    c.customer_state,
    s.seller_state,
    s.seller_city
FROM raw.order_items i
JOIN raw.orders o     ON o.order_id = i.order_id
JOIN raw.customers c  ON c.customer_id = o.customer_id
LEFT JOIN raw.products p ON p.product_id = i.product_id
LEFT JOIN raw.product_category_name_translation t
       ON t.product_category_name = p.product_category_name
LEFT JOIN raw.sellers s  ON s.seller_id = i.seller_id;

-- One row per calendar month from the first to the last purchase month, including months
-- with zero orders (2016-11), so gaps are visible rather than silently skipped.
CREATE VIEW analytics.data_coverage AS
SELECT
    m.month::date                                            AS month,
    count(o.order_id)::int                                   AS orders_count,
    count(o.order_id) < 500                                  AS is_partial,
    m.month >= DATE '2017-01-01' AND m.month < DATE '2018-09-01' AS in_analysis_window
FROM generate_series(
        (SELECT date_trunc('month', min(order_purchase_timestamp)) FROM raw.orders),
        (SELECT date_trunc('month', max(order_purchase_timestamp)) FROM raw.orders),
        interval '1 month') AS m(month)
LEFT JOIN raw.orders o
       ON date_trunc('month', o.order_purchase_timestamp) = m.month
GROUP BY m.month;

-- Documentation stored in the database: used to generate the validator allow-list (M4)
-- and the view documentation in prompts (M5), so the two cannot drift apart.
COMMENT ON SCHEMA analytics IS 'Curated, read-only views. The only data the agent can query.';
COMMENT ON VIEW analytics.orders IS 'One row per order. Business definitions applied; see glossary.';
COMMENT ON VIEW analytics.order_items IS 'One row per order item, with order, customer and seller attributes.';
COMMENT ON VIEW analytics.payments IS 'One row per order that has payments. Safe to join to orders or items.';
COMMENT ON VIEW analytics.reviews IS 'One row per reviewed order: the latest answered review. No review text.';
COMMENT ON VIEW analytics.sellers IS 'One row per seller.';
COMMENT ON VIEW analytics.data_coverage IS 'One row per month: order volume and partial-period flag.';

COMMENT ON COLUMN analytics.orders.customer_unique_id IS 'The person. Use this, not a per-order id, to count customers.';
COMMENT ON COLUMN analytics.orders.purchase_month IS 'First day of the purchase month (order month).';
COMMENT ON COLUMN analytics.orders.is_sale IS 'True unless status is canceled or unavailable. Revenue counts sales only.';
COMMENT ON COLUMN analytics.orders.is_delivered IS 'Status delivered and a customer delivery timestamp exists.';
COMMENT ON COLUMN analytics.orders.is_late IS 'Delivered date later than estimated date (dates, not timestamps). NULL if not delivered.';
COMMENT ON COLUMN analytics.orders.days_late IS 'Delivered date minus estimated date; negative = early. NULL if not delivered.';
COMMENT ON COLUMN analytics.orders.seller_handling_days IS 'Carrier hand-off minus purchase, in days. NULL if missing or negative.';
COMMENT ON COLUMN analytics.orders.carrier_transit_days IS 'Customer delivery minus carrier hand-off, in days. NULL if missing or negative.';
COMMENT ON COLUMN analytics.orders.promised_days IS 'Estimated delivery date minus purchase, in days.';
COMMENT ON COLUMN analytics.orders.delivery_days IS 'Customer delivery minus purchase, in days.';
COMMENT ON COLUMN analytics.orders.items_revenue IS 'Sum of item prices, excluding freight; 0 if the order has no items.';
COMMENT ON COLUMN analytics.orders.freight_total IS 'Sum of item freight; never part of revenue.';
COMMENT ON COLUMN analytics.orders.payment_total IS 'Sum of payments; NULL if the order has no payment row.';
COMMENT ON COLUMN analytics.orders.review_score IS 'Score (1-5) of the latest answered review; NULL if not reviewed.';
COMMENT ON COLUMN analytics.orders.seller_count IS 'Distinct sellers in the order; >1 means a multi-seller order.';
COMMENT ON COLUMN analytics.order_items.category IS 'English category; unknown if missing; Portuguese name if untranslated.';
COMMENT ON COLUMN analytics.order_items.price IS 'Item price, excluding freight. Revenue = sum(price) where is_sale.';
COMMENT ON COLUMN analytics.payments.payment_types IS 'Distinct payment types joined with +, e.g. credit_card+voucher.';
COMMENT ON COLUMN analytics.payments.primary_payment_type IS 'Payment type of the largest payment row.';
COMMENT ON COLUMN analytics.data_coverage.is_partial IS 'Fewer than 500 orders in the month: results need a warning.';
COMMENT ON COLUMN analytics.data_coverage.in_analysis_window IS 'Month between January 2017 and August 2018.';

-- Grants: explicit and minimal (technical design, section 6.3).
GRANT USAGE ON SCHEMA analytics TO oi_agent, oi_eval;
GRANT SELECT ON ALL TABLES IN SCHEMA analytics TO oi_agent, oi_eval;
GRANT USAGE ON SCHEMA raw TO oi_eval;
GRANT SELECT ON ALL TABLES IN SCHEMA raw TO oi_eval;
