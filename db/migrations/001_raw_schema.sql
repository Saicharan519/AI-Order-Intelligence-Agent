-- 001: typed copies of the eight Olist source tables (technical design, section 6.2).
-- "raw" means faithful to the source: source column names are kept (including the
-- product_name_lenght typo), and no foreign keys are enforced. Relationship problems are
-- measured by scripts/check_counts.py instead of failing the load.

CREATE SCHEMA raw;

CREATE TABLE raw.orders (
    order_id                      text PRIMARY KEY,
    customer_id                   text NOT NULL,
    order_status                  text NOT NULL,
    order_purchase_timestamp      timestamp NOT NULL,
    order_approved_at             timestamp,
    order_delivered_carrier_date  timestamp,
    order_delivered_customer_date timestamp,
    -- always midnight in the source: a date stored as a timestamp
    order_estimated_delivery_date timestamp NOT NULL
);

CREATE TABLE raw.order_items (
    order_id            text NOT NULL,
    order_item_id       smallint NOT NULL,
    product_id          text NOT NULL,
    seller_id           text NOT NULL,
    shipping_limit_date timestamp NOT NULL,
    price               numeric(12,2) NOT NULL,
    freight_value       numeric(12,2) NOT NULL,
    PRIMARY KEY (order_id, order_item_id)
);

CREATE TABLE raw.order_payments (
    order_id             text NOT NULL,
    payment_sequential   smallint NOT NULL,
    payment_type         text NOT NULL,
    payment_installments smallint NOT NULL,
    payment_value        numeric(12,2) NOT NULL,
    PRIMARY KEY (order_id, payment_sequential)
);

-- review_id is NOT unique in the source, so a surrogate key is used.
-- Comment text is kept here but never exposed through the analytics views.
CREATE TABLE raw.order_reviews (
    review_row_id           integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    review_id               text NOT NULL,
    order_id                text NOT NULL,
    review_score            smallint NOT NULL CHECK (review_score BETWEEN 1 AND 5),
    review_comment_title    text,
    review_comment_message  text,
    review_creation_date    timestamp NOT NULL,
    review_answer_timestamp timestamp
);

CREATE TABLE raw.customers (
    customer_id              text PRIMARY KEY,
    customer_unique_id       text NOT NULL,
    customer_zip_code_prefix text NOT NULL,  -- text: keeps leading zeros
    customer_city            text NOT NULL,
    customer_state           text NOT NULL
);

CREATE TABLE raw.products (
    product_id                 text PRIMARY KEY,
    product_category_name      text,
    product_name_lenght        integer,
    product_description_lenght integer,
    product_photos_qty         integer,
    product_weight_g           integer,
    product_length_cm          integer,
    product_height_cm          integer,
    product_width_cm           integer
);

CREATE TABLE raw.sellers (
    seller_id              text PRIMARY KEY,
    seller_zip_code_prefix text NOT NULL,
    seller_city            text NOT NULL,
    seller_state           text NOT NULL
);

CREATE TABLE raw.product_category_name_translation (
    product_category_name         text PRIMARY KEY,
    product_category_name_english text NOT NULL
);
