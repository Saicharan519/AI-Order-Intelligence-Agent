"""Synthetic mini Olist dataset (technical design 8.6 and 9.2).

Deterministic (fixed seed) and small: 20 months x 400 delivered orders, plus a few
non-delivered and out-of-window orders. The CSVs have the exact Olist file names and
headers, so the normal migrations and loader build the database (scripts/build_mini_db.py).
The CSVs are generated, not committed: this file is the source of truth.

Baseline lateness is exactly 5% inside every (month, state) group, so a control month sits
exactly at its baseline and a detection cannot come from random noise.

Planted anomalies (PLANTS), applied after the estimated delivery date is fixed, so the
promise is unchanged and only the planted stage moves:
  * transit:  +10 carrier transit days for customers in RJ, March 2018;
  * handling: +5 seller handling days for PLANT_SELLER (about 30% of orders), October 2017.

Data traps (TRAPS), matching those found in the real data in M1: multi-payment orders,
duplicate reviews (the latest answer wins), a product with no category, an untranslated
category, multi-seller orders, a same-day delivery, non-delivered statuses including
"delivered" with no delivery date, an order with no review, and empty months (2016-11 and
2016-12) between the first order and the analysis window.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import random
from pathlib import Path

SEED = 20261016
ORDERS_PER_MONTH = 400
LATE_SHARE = 0.05
# Exact orders per state per month (sums to 400).
STATE_COUNTS = {"SP": 160, "RJ": 120, "MG": 60, "BA": 40, "PR": 20}
CITIES = {
    "SP": ("sao paulo", "01310"),
    "RJ": ("rio de janeiro", "20040"),
    "MG": ("belo horizonte", "30130"),
    "BA": ("salvador", "40020"),
    "PR": ("curitiba", "80010"),
}


def hex_id(*parts: object) -> str:
    """Olist-style 32-character hexadecimal id."""
    return hashlib.md5("|".join(map(str, parts)).encode()).hexdigest()  # noqa: S324


PLANT_SELLER = hex_id("seller", "plant")
OTHER_SELLERS = [hex_id("seller", i) for i in range(5)]
TINY_SELLER = hex_id("seller", "tiny")  # appears only in multi-seller orders
SELLER_STATES = ["SP", "SP", "MG", "PR", "RJ", "SP"]  # PLANT_SELLER first
PLANT_SELLER_SHARE = 0.30

PLANTS = {
    "transit": {"month": "2018-03", "state": "RJ", "extra_transit_days": 10},
    "handling": {"month": "2017-10", "seller": PLANT_SELLER, "extra_handling_days": 5},
}

CATEGORIES = {  # Portuguese name -> English translation
    "cama_mesa_banho": "bed_bath_table",
    "beleza_saude": "health_beauty",
    "esporte_lazer": "sports_leisure",
    "informatica_acessorios": "computers_accessories",
    "moveis_decoracao": "furniture_decor",
    "utilidades_domesticas": "housewares",
    "relogios_presentes": "watches_gifts",
    "brinquedos": "toys",
}
UNTRANSLATED_CATEGORY = "pc_gamer"

TRAPS = {
    "multi_payment_order": hex_id("trap", "multi_payment"),
    "duplicate_review_order": hex_id("trap", "duplicate_review"),
    "null_category_product": hex_id("product", "null_category"),
    "untranslated_product": hex_id("product", UNTRANSLATED_CATEGORY),
    "multi_seller_order": hex_id("trap", "multi_seller"),
    "same_day_order": hex_id("trap", "same_day"),
    "delivered_no_date_order": hex_id("trap", "delivered_no_date"),
    "no_review_order": hex_id("trap", "no_review"),
}

HEADERS = {
    "olist_orders_dataset.csv": [
        "order_id",
        "customer_id",
        "order_status",
        "order_purchase_timestamp",
        "order_approved_at",
        "order_delivered_carrier_date",
        "order_delivered_customer_date",
        "order_estimated_delivery_date",
    ],
    "olist_order_items_dataset.csv": [
        "order_id",
        "order_item_id",
        "product_id",
        "seller_id",
        "shipping_limit_date",
        "price",
        "freight_value",
    ],
    "olist_order_payments_dataset.csv": [
        "order_id",
        "payment_sequential",
        "payment_type",
        "payment_installments",
        "payment_value",
    ],
    "olist_order_reviews_dataset.csv": [
        "review_id",
        "order_id",
        "review_score",
        "review_comment_title",
        "review_comment_message",
        "review_creation_date",
        "review_answer_timestamp",
    ],
    "olist_customers_dataset.csv": [
        "customer_id",
        "customer_unique_id",
        "customer_zip_code_prefix",
        "customer_city",
        "customer_state",
    ],
    "olist_products_dataset.csv": [
        "product_id",
        "product_category_name",
        "product_name_lenght",
        "product_description_lenght",
        "product_photos_qty",
        "product_weight_g",
        "product_length_cm",
        "product_height_cm",
        "product_width_cm",
    ],
    "olist_sellers_dataset.csv": [
        "seller_id",
        "seller_zip_code_prefix",
        "seller_city",
        "seller_state",
    ],
    "product_category_name_translation.csv": [
        "product_category_name",
        "product_category_name_english",
    ],
}
TABLE_OF = {  # file -> raw table, for the loader's expected counts
    "olist_orders_dataset.csv": "orders",
    "olist_order_items_dataset.csv": "order_items",
    "olist_order_payments_dataset.csv": "order_payments",
    "olist_order_reviews_dataset.csv": "order_reviews",
    "olist_customers_dataset.csv": "customers",
    "olist_products_dataset.csv": "products",
    "olist_sellers_dataset.csv": "sellers",
    "product_category_name_translation.csv": "product_category_name_translation",
}


def months() -> list[str]:
    out, d = [], dt.date(2017, 1, 1)
    while d < dt.date(2018, 9, 1):
        out.append(d.strftime("%Y-%m"))
        d = dt.date(d.year + d.month // 12, d.month % 12 + 1, 1)
    return out


def ts(t: dt.datetime | None) -> str:
    return "" if t is None else t.strftime("%Y-%m-%d %H:%M:%S")


def midnight(d: dt.date) -> dt.datetime:
    return dt.datetime(d.year, d.month, d.day)


class Builder:
    def __init__(self, plants: bool) -> None:
        self.rng = random.Random(SEED)  # noqa: S311  seeded on purpose: reproducible data
        self.plants = plants
        self.rows: dict[str, list[list]] = {f: [] for f in HEADERS}
        self.products: list[str] = []
        self.n = 0

    def add_reference_tables(self) -> None:
        sellers = [PLANT_SELLER, *OTHER_SELLERS]
        for sid, state in zip(sellers, SELLER_STATES, strict=True):
            city, zip_ = CITIES[state]
            self.rows["olist_sellers_dataset.csv"].append([sid, zip_, city, state])
        self.rows["olist_sellers_dataset.csv"].append([TINY_SELLER, "04538", "sao paulo", "SP"])
        for pt, en in CATEGORIES.items():
            self.rows["product_category_name_translation.csv"].append([pt, en])
            for i in range(5):
                self._product(hex_id("product", pt, i), pt)
        self._product(TRAPS["null_category_product"], "")
        self._product(TRAPS["untranslated_product"], UNTRANSLATED_CATEGORY)

    def _product(self, pid: str, category: str) -> None:
        r = self.rng
        self.products.append(pid)
        dims = [r.randint(10, 60) for _ in range(3)]
        name_len = "" if not category else r.randint(20, 60)  # source quirk: nulls together
        desc_len = "" if not category else r.randint(100, 2000)
        photos = "" if not category else r.randint(1, 5)
        self.rows["olist_products_dataset.csv"].append(
            [pid, category, name_len, desc_len, photos, r.randint(100, 5000), *dims]
        )

    def order(
        self,
        month: str,
        state: str,
        seller: str,
        *,
        late: bool,
        status: str = "delivered",
        order_id: str | None = None,
        sellers_extra: tuple[str, ...] = (),
        same_day: bool = False,
        delivered_date: bool = True,
        review: bool = True,
        product: str | None = None,
    ) -> str:
        r = self.rng
        self.n += 1
        oid = order_id or hex_id("order", self.n)
        cid = hex_id("customer", self.n)
        uid = hex_id("unique", self.n % 7000)  # some customers order more than once
        y, m = map(int, month.split("-"))
        purchase = dt.datetime(y, m, 1) + dt.timedelta(
            days=r.randint(0, 27), seconds=r.randint(8 * 3600, 22 * 3600)
        )
        approved = purchase + dt.timedelta(minutes=r.randint(10, 600))
        if same_day:
            carrier = purchase + dt.timedelta(hours=1)
            delivered = purchase + dt.timedelta(hours=1, minutes=30)
        else:
            carrier = purchase + dt.timedelta(days=r.uniform(1, 4))
            delivered = carrier + dt.timedelta(days=r.uniform(5, 10))
        if late:
            estimated = midnight(delivered.date() - dt.timedelta(days=r.randint(1, 5)))
        else:
            estimated = midnight(delivered.date() + dt.timedelta(days=r.randint(2, 10)))

        if self.plants and status == "delivered":
            t, h = PLANTS["transit"], PLANTS["handling"]
            if month == t["month"] and state == t["state"]:
                delivered += dt.timedelta(days=t["extra_transit_days"])
            if month == h["month"] and seller == h["seller"]:
                carrier += dt.timedelta(days=h["extra_handling_days"])
                delivered += dt.timedelta(days=h["extra_handling_days"])

        if status == "canceled":
            carrier = delivered = None
        elif status in ("shipped", "unavailable"):
            delivered = None
            carrier = None if status == "unavailable" else carrier
        elif not delivered_date:
            delivered = None

        city, zip_ = CITIES[state]
        self.rows["olist_customers_dataset.csv"].append([cid, uid, zip_, city, state])
        self.rows["olist_orders_dataset.csv"].append(
            [
                oid,
                cid,
                status,
                ts(purchase),
                ts(approved),
                ts(carrier),
                ts(delivered),
                ts(estimated),
            ]
        )

        total = 0.0
        for i, sid in enumerate((seller, *sellers_extra), start=1):
            price = round(r.uniform(20, 400), 2)
            freight = round(r.uniform(8, 40), 2)
            total += price + freight
            pid = product if (product and i == 1) else r.choice(self.products[:-2])
            self.rows["olist_order_items_dataset.csv"].append(
                [
                    oid,
                    i,
                    pid,
                    sid,
                    ts(purchase + dt.timedelta(days=3)),
                    f"{price:.2f}",
                    f"{freight:.2f}",
                ]
            )

        if oid == TRAPS["multi_payment_order"]:
            voucher = round(total * 0.3, 2)
            self.rows["olist_order_payments_dataset.csv"] += [
                [oid, 1, "credit_card", 3, f"{total - voucher:.2f}"],
                [oid, 2, "voucher", 1, f"{voucher:.2f}"],
            ]
        else:
            ptype = r.choice(["credit_card", "credit_card", "credit_card", "boleto", "debit_card"])
            installments = r.randint(1, 8) if ptype == "credit_card" else 1
            self.rows["olist_order_payments_dataset.csv"].append(
                [oid, 1, ptype, installments, f"{total:.2f}"]
            )

        if review and oid != TRAPS["no_review_order"]:
            base = delivered or (purchase + dt.timedelta(days=20))
            created = midnight(base.date() + dt.timedelta(days=1))
            if status != "delivered" or delivered is None:
                score = 1
            elif delivered.date() > estimated.date():
                score = r.choice([1, 1, 2, 3])
            else:
                score = r.choice([5, 5, 4, 4, 3])
            if oid == TRAPS["duplicate_review_order"]:  # older answer first; the later one wins
                self._review(oid, 5, created, created + dt.timedelta(days=1), "first")
                self._review(oid, 2, created, created + dt.timedelta(days=4), "second")
            else:
                self._review(oid, score, created, created + dt.timedelta(days=r.randint(1, 3)))
        return oid

    def _review(self, oid, score, created, answered, tag="") -> None:
        comment = "" if self.rng.random() < 0.6 else "produto chegou, obrigado"
        self.rows["olist_order_reviews_dataset.csv"].append(
            [hex_id("review", oid, tag), oid, score, "", comment, ts(created), ts(answered)]
        )

    def month_orders(self, month: str, idx: int) -> None:
        r = self.rng
        n_plant = round(ORDERS_PER_MONTH * PLANT_SELLER_SHARE)
        sellers = [PLANT_SELLER] * n_plant + [
            OTHER_SELLERS[i % len(OTHER_SELLERS)] for i in range(ORDERS_PER_MONTH - n_plant)
        ]
        r.shuffle(sellers)
        k = 0
        for state, count in STATE_COUNTS.items():
            n_late = round(count * LATE_SHARE)
            for j in range(count):
                self.order(month, state, sellers[k], late=j < n_late)
                k += 1
        # Non-delivered orders (SP), outside the delivered population used by the playbooks.
        for status in ("canceled", "shipped", "unavailable"):
            self.order(month, "SP", r.choice(OTHER_SELLERS), late=False, status=status)
        if idx == 2:
            self.order(
                month, "SP", OTHER_SELLERS[0], late=False, order_id=TRAPS["multi_payment_order"]
            )
            self.order(
                month, "MG", OTHER_SELLERS[1], late=False, order_id=TRAPS["duplicate_review_order"]
            )
            self.order(
                month,
                "SP",
                OTHER_SELLERS[2],
                late=False,
                order_id=TRAPS["same_day_order"],
                same_day=True,
            )
            self.order(
                month,
                "SP",
                OTHER_SELLERS[3],
                late=False,
                order_id=TRAPS["delivered_no_date_order"],
                delivered_date=False,
            )
            self.order(month, "BA", OTHER_SELLERS[4], late=False, order_id=TRAPS["no_review_order"])
            self.order(
                month, "PR", OTHER_SELLERS[0], late=False, product=TRAPS["null_category_product"]
            )
            self.order(
                month, "PR", OTHER_SELLERS[1], late=False, product=TRAPS["untranslated_product"]
            )
        if idx == 4:
            self.order(
                month,
                "SP",
                OTHER_SELLERS[0],
                late=False,
                order_id=TRAPS["multi_seller_order"],
                sellers_extra=(TINY_SELLER,),
            )


def generate(out_dir: Path, plants: bool = True) -> dict[str, int]:
    """Write the CSVs to out_dir; return the expected row count per raw table."""
    b = Builder(plants)
    b.add_reference_tables()
    for _ in range(5):  # a few orders before the window: 2016-11 and 2016-12 stay empty
        b.order("2016-10", "SP", OTHER_SELLERS[0], late=False)
    for idx, month in enumerate(months()):
        b.month_orders(month, idx)
    b.order("2018-09", "SP", OTHER_SELLERS[1], late=False, status="canceled")

    out_dir.mkdir(parents=True, exist_ok=True)
    for name, header in HEADERS.items():
        with (out_dir / name).open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(header)
            w.writerows(b.rows[name])
    return {TABLE_OF[name]: len(rows) for name, rows in b.rows.items()}
