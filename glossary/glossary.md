# Business glossary

Version 1.0 (2026-10-15). Source: PRD section 6. These definitions are implemented once, in the `analytics` views, and are shown to the model and to users. If a definition changes, the view, this file, and the PRD change together.

## Data window and dates

| Term | Definition | Where implemented |
|---|---|---|
| Analysis window | January 2017 to August 2018. Data outside it is sparse. | Prompt rules; `data_coverage` |
| "Today" | 2018-08-31. Relative dates ("last month", "this year") are resolved against this date, so "last month" means July 2018. | Prompt rules |
| Order month | Month of the purchase timestamp. | `orders.purchase_month` (first day of the month) |
| Partial period | A month with fewer than 500 orders. Results for it carry a warning. November 2016 has zero orders. | `data_coverage.is_partial` |
| Currency | Brazilian reais (BRL, R$). Assumed; the source does not state it. | Answer wording |

## Orders and delivery

| Term | Definition | Where implemented |
|---|---|---|
| Delivered order | `order_status = 'delivered'` and a customer delivery timestamp exists. | `orders.is_delivered` |
| Late | A delivered order whose delivery **date** is later than its estimated delivery **date**. Dates are compared, not timestamps, because the estimate is always midnight: comparing timestamps would wrongly mark same-day deliveries as late. NULL for orders that are not delivered. | `orders.is_late` |
| On time | A delivered order that is not late. | `orders.is_late = false` |
| Late rate | Late orders divided by delivered orders. Never divide by all orders. | Query pattern |
| Days late | Delivery date minus estimated date, in days. Negative means early. NULL if not delivered. | `orders.days_late` |
| Seller handling days | Carrier hand-off timestamp minus purchase timestamp, in days (fractional). | `orders.seller_handling_days` |
| Carrier transit days | Customer delivery timestamp minus carrier hand-off timestamp, in days. | `orders.carrier_transit_days` |
| Promised days | Estimated delivery date minus purchase timestamp, in days. | `orders.promised_days` |
| Delivery days | Customer delivery timestamp minus purchase timestamp, in days. | `orders.delivery_days` |
| Impossible durations | A stage duration below zero is a recording error (166 orders were handed to the carrier before purchase; 23 were delivered before hand-off). Such durations are NULL. | Stage-day columns |

## Money

| Term | Definition | Where implemented |
|---|---|---|
| Sale | An order whose status is not `canceled` or `unavailable`. | `orders.is_sale`, `order_items.is_sale` |
| Revenue | Sum of item `price` over sales, **excluding freight**. Including canceled and unavailable orders would change 2017 revenue by 0.77%. | `orders.items_revenue`, `order_items.price` |
| Freight | Sum of item `freight_value`. Reported separately, never inside revenue. | `orders.freight_total` |
| Payment total | Sum of payment rows for an order. One row per order in `payments`, so joining it never multiplies item rows. | `payments.payment_total` |
| Average order value | Revenue divided by the number of sale orders that have items. | Query pattern |

## People, sellers, products, reviews

| Term | Definition | Where implemented |
|---|---|---|
| Customer | A person: `customer_unique_id`. Never `customer_id`, which is created per order. | `orders.customer_unique_id` |
| Repeat customer | A customer with more than one order. About 3% of customers. | Query pattern |
| Category | English category name. Products without a category are `unknown`. The two categories without an English translation keep their Portuguese names. | `order_items.category` |
| Review score | Score of the latest answered review for the order (one per order). Review text is never available. | `orders.review_score`, `reviews` |
| Ranking eligibility | A seller or group needs at least 30 orders to appear in a ranking; the sample size is always shown. | Query pattern |
| Multi-seller order | An order with items from more than one seller (1,278 orders). Order-level outcomes such as lateness are not attributed to a single seller without saying so. | `orders.seller_count` |
| Baseline (investigations) | The pooled value over all other months in the analysis window, excluding the period under investigation. | Playbooks (M7) |
