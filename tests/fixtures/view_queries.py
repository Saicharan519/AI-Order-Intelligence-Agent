"""Legitimate queries over the analytics views, covering every SQL construct the golden
references need (DISTINCT ON, FILTER, WITHIN GROUP, windows, CTEs, set operations,
correlated subqueries, casts, intervals, string functions).

Used as POSITIVE cases for the validator and to calibrate the executor's EXPLAIN ceiling.
These are test fixtures only: they are never shown to the model (that would contaminate
the evaluation).
"""

VIEW_QUERIES: dict[str, str] = {
    "count_sellers_sp": "SELECT count(*) FROM sellers WHERE seller_state = 'SP'",
    "order_lookup": (
        "SELECT order_status, delivered_ts::date FROM orders "
        "WHERE order_id = 'e481f51cbdc54678b7cc49136f2d6af7'"
    ),
    "late_rate": (
        "SELECT round(100.0 * count(*) FILTER (WHERE is_late) / count(*), 2) "
        "FROM orders WHERE is_delivered"
    ),
    "revenue_2017": (
        "SELECT sum(price) FROM order_items WHERE is_sale "
        "AND purchase_date >= DATE '2017-01-01' AND purchase_date < DATE '2018-01-01'"
    ),
    "aov_2017": (
        "SELECT round(sum(items_revenue) / count(*), 2) FROM orders "
        "WHERE is_sale AND item_count > 0 AND purchase_month BETWEEN '2017-01-01' AND '2017-12-01'"
    ),
    "monthly_orders": (
        "SELECT purchase_month, count(*) AS orders FROM orders "
        "WHERE purchase_month >= '2017-01-01' AND purchase_month < '2018-01-01' "
        "GROUP BY purchase_month ORDER BY purchase_month"
    ),
    "monthly_late_cte": (
        "WITH m AS (SELECT purchase_month, avg(is_late::int) AS r FROM orders "
        "WHERE is_delivered GROUP BY purchase_month) "
        "SELECT purchase_month, round(100 * r, 1) FROM m ORDER BY 1"
    ),
    "top_categories": (
        "SELECT category, sum(price) AS revenue, count(DISTINCT order_id) AS orders "
        "FROM order_items WHERE is_sale AND extract(year FROM purchase_date) = 2017 "
        "GROUP BY category ORDER BY revenue DESC LIMIT 5"
    ),
    "share_window": (
        "SELECT category, round(100 * sum(price) / sum(sum(price)) OVER (), 1) AS share "
        "FROM order_items WHERE is_sale GROUP BY category ORDER BY share DESC LIMIT 10"
    ),
    "seller_rank": (
        "SELECT seller_id, count(DISTINCT order_id) AS n, "
        "rank() OVER (ORDER BY count(DISTINCT order_id) DESC) AS rnk "
        "FROM order_items GROUP BY seller_id HAVING count(DISTINCT order_id) >= 30 "
        "ORDER BY rnk LIMIT 10"
    ),
    "worst_sellers_cte_join": (
        "WITH s AS (SELECT DISTINCT i.seller_id, o.order_id, o.is_late FROM order_items i "
        "JOIN orders o ON o.order_id = i.order_id WHERE o.is_delivered) "
        "SELECT seller_id, round(100.0 * avg(is_late::int), 2) AS late_pct FROM s "
        "GROUP BY seller_id HAVING count(*) >= 30 ORDER BY late_pct DESC LIMIT 5"
    ),
    "payments_join_no_fanout": (
        "SELECT sum(i.price) FROM order_items i JOIN payments p ON p.order_id = i.order_id "
        "WHERE p.payment_types LIKE '%credit_card%' AND i.is_sale "
        "AND i.purchase_date >= DATE '2017-01-01' AND i.purchase_date < DATE '2018-01-01'"
    ),
    "payment_type_counts": (
        "SELECT primary_payment_type, count(*) FROM payments GROUP BY 1 ORDER BY 2 DESC"
    ),
    "repeat_customers": (
        "SELECT round(100.0 * count(*) FILTER (WHERE n > 1) / count(*), 2) FROM "
        "(SELECT customer_unique_id, count(*) AS n FROM orders GROUP BY customer_unique_id) c"
    ),
    "median_delivery": (
        "SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY delivery_days) "
        "FROM orders WHERE is_delivered"
    ),
    "review_by_lateness": (
        "SELECT CASE WHEN is_late THEN 'late' ELSE 'on time' END AS bucket, "
        "round(avg(review_score), 2) FROM orders WHERE is_delivered GROUP BY 1"
    ),
    "distinct_on_latest": (
        "SELECT DISTINCT ON (customer_state) customer_state, order_id, purchase_ts "
        "FROM orders ORDER BY customer_state, purchase_ts DESC"
    ),
    "correlated_exists": (
        "SELECT count(*) FROM orders o WHERE EXISTS (SELECT 1 FROM payments p "
        "WHERE p.order_id = o.order_id AND p.payment_count > 1)"
    ),
    "union_years": (
        "SELECT 2017 AS year, count(*) FROM orders WHERE extract(year FROM purchase_ts) = 2017 "
        "UNION ALL "
        "SELECT 2018, count(*) FROM orders WHERE extract(year FROM purchase_ts) = 2018"
    ),
    "relative_date_interval": (
        "SELECT count(*) FROM orders WHERE purchase_ts >= DATE '2018-08-31' - INTERVAL '30 days'"
    ),
    "partial_months": (
        "SELECT month, orders_count FROM data_coverage WHERE is_partial ORDER BY month"
    ),
    "string_functions": (
        "SELECT upper(seller_state), lower(seller_city), length(seller_city), "
        "coalesce(nullif(seller_city, ''), 'unknown'), seller_city || '-' || seller_state "
        "FROM sellers ORDER BY 1 LIMIT 3"
    ),
    "date_functions": (
        "SELECT date_trunc('month', purchase_ts)::date, to_char(purchase_ts, 'YYYY-MM'), "
        "extract(dow FROM purchase_ts), greatest(promised_days, 0) FROM orders LIMIT 3"
    ),
    "in_list_states": (
        "SELECT customer_state, count(*) FROM orders WHERE customer_state IN ('SP', 'RJ', 'MG') "
        "GROUP BY 1"
    ),
    "stage_days_compare": (
        "SELECT purchase_month = DATE '2018-03-01' AS is_march, avg(seller_handling_days), "
        "avg(carrier_transit_days), avg(promised_days) FROM orders "
        "WHERE is_delivered AND purchase_month BETWEEN '2017-01-01' AND '2018-08-01' GROUP BY 1"
    ),
    "string_agg_types": (
        "SELECT payment_types, count(*) FROM payments GROUP BY 1 ORDER BY 2 DESC LIMIT 5"
    ),
}
