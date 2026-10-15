"""Independent cross-check of golden references in pandas (technical design 8.1, T-3.4).

The raw tables are loaded into pandas and each answer is re-derived with dataframe
operations instead of SQL. Agreement between two independent implementations is
evidence that the reference is right; a disagreement means one of them is wrong and
must be resolved before the golden set is trusted.

    python eval/crosscheck.py
"""

from __future__ import annotations

import sys
from collections.abc import Callable

import pandas as pd

from orderintel.db.connect import connect_eval
from orderintel.evaluation.compare import compare_results
from orderintel.evaluation.golden import load_golden

TABLES = [
    "orders",
    "order_items",
    "order_payments",
    "order_reviews",
    "customers",
    "products",
    "sellers",
    "product_category_name_translation",
]

Frames = dict[str, pd.DataFrame]


def load_frames() -> Frames:
    frames = {}
    with connect_eval() as conn:
        for t in TABLES:
            cur = conn.execute(f"SELECT * FROM raw.{t}")  # noqa: S608
            frames[t] = pd.DataFrame(cur.fetchall(), columns=[d.name for d in cur.description])
    for col in [
        "order_purchase_timestamp",
        "order_delivered_customer_date",
        "order_estimated_delivery_date",
        "order_delivered_carrier_date",
    ]:
        frames["orders"][col] = pd.to_datetime(frames["orders"][col])
    for col in ["price", "freight_value"]:
        frames["order_items"][col] = frames["order_items"][col].astype(float)
    frames["order_payments"]["payment_value"] = frames["order_payments"]["payment_value"].astype(
        float
    )
    return frames


# ---------- shared helpers (pandas versions of the glossary definitions) ----------
def sales(f: Frames) -> pd.DataFrame:
    o = f["orders"]
    return o[~o.order_status.isin(["canceled", "unavailable"])]


def delivered(f: Frames) -> pd.DataFrame:
    o = f["orders"]
    d = o[(o.order_status == "delivered") & o.order_delivered_customer_date.notna()].copy()
    d["late"] = (
        d.order_delivered_customer_date.dt.normalize()
        > d.order_estimated_delivery_date.dt.normalize()
    )
    return d


def in_year(df: pd.DataFrame, year: int) -> pd.DataFrame:
    return df[df.order_purchase_timestamp.dt.year == year]


def sale_items(f: Frames) -> pd.DataFrame:
    return f["order_items"].merge(sales(f)[["order_id", "order_purchase_timestamp"]], on="order_id")


def latest_reviews(f: Frames) -> pd.DataFrame:
    r = f["order_reviews"].sort_values(
        ["order_id", "review_answer_timestamp", "review_creation_date", "review_row_id"]
    )
    return r.groupby("order_id").tail(1)


def rate(mask: pd.Series) -> float:
    return round(100.0 * mask.sum() / len(mask), 2)


def months(df: pd.DataFrame) -> pd.Series:
    return df.order_purchase_timestamp.dt.to_period("M").dt.to_timestamp().dt.date


# ---------- independent implementations ----------
def lookup_01(f):
    return [(int((f["sellers"].seller_state == "SP").sum()),)]


def lookup_06(f):
    p = f["order_payments"]
    return [(p[p.order_id == "00bd50cdd31bd22e9081e6e2d5b3577b"].payment_value.sum(),)]


def lookup_07(f):
    r = latest_reviews(f)
    return [(int(r[r.order_id == "013056cfe49763c6f66bda03396c5ee3"].review_score.iloc[0]),)]


def agg_02(f):
    return [(len(delivered(f)),)]


def agg_03(f):
    return [(in_year(sale_items(f), 2018).price.sum(),)]


def agg_04(f):
    return [(rate(delivered(f).late),)]


def agg_06(f):
    return [(in_year(sale_items(f), 2017).seller_id.nunique(),)]


def agg_08(f):
    p = f["order_payments"]
    voucher_orders = p[p.payment_type == "voucher"].order_id.nunique()
    return [(round(100.0 * voucher_orders / p.order_id.nunique(), 2),)]


def agg_09(f):
    d = delivered(f)
    days = (d.order_delivered_customer_date - d.order_purchase_timestamp).dt.total_seconds() / 86400
    return [(round(days.mean(), 2),)]


def agg_11(f):
    s = in_year(sale_items(f), 2017)
    return [(round(s.price.sum() / s.order_id.nunique(), 2),)]


def agg_12(f):
    c = f["customers"]
    return [(c[c.customer_state == "RJ"].customer_unique_id.nunique(),)]


def agg_14(f):
    return [(rate(in_year(delivered(f), 2018).late),)]


def trend_01(f):
    o = in_year(f["orders"], 2017)
    return list(o.groupby(months(o)).size().items())


def trend_03(f):
    d = delivered(f)
    d = d[
        (d.order_purchase_timestamp >= "2018-01-01") & (d.order_purchase_timestamp < "2018-09-01")
    ]
    return [(m, rate(g.late)) for m, g in d.groupby(months(d))]


def trend_05(f):
    o = f["orders"].merge(f["customers"], on="customer_id")
    return list(o.customer_state.value_counts().head(5).items())


def trend_07(f):
    p = f["products"].merge(
        f["product_category_name_translation"], on="product_category_name", how="left"
    )
    p["category"] = p.product_category_name_english.fillna(p.product_category_name).fillna(
        "unknown"
    )
    s = in_year(sale_items(f), 2018).merge(p[["product_id", "category"]], on="product_id")
    return list(s.groupby("category").price.sum().sort_values(ascending=False).head(10).items())


def trend_08(f):
    p = f["order_payments"]
    return list(p.groupby("payment_type").order_id.nunique().sort_values(ascending=False).items())


def trend_09(f):
    d = delivered(f).merge(f["customers"], on="customer_id")
    d["days"] = (
        d.order_delivered_customer_date - d.order_purchase_timestamp
    ).dt.total_seconds() / 86400
    top = d.groupby("customer_state").days.mean().sort_values(ascending=False).head(5)
    return [(s, round(v, 2)) for s, v in top.items()]


def trap_01(f):
    p = f["order_payments"]
    cc_orders = set(p[p.payment_type == "credit_card"].order_id)
    s = in_year(sale_items(f), 2017)
    return [(s[s.order_id.isin(cc_orders)].price.sum(),)]


def trap_02(f):
    o = in_year(f["orders"], 2017).merge(f["customers"], on="customer_id")
    return [(o.customer_unique_id.nunique(),)]


def trap_04(f):
    d = delivered(f)
    feb = d[
        (d.order_purchase_timestamp >= "2018-02-01") & (d.order_purchase_timestamp < "2018-03-01")
    ]
    return [(rate(feb.late),)]


def trap_06(f):
    d = delivered(f)[["order_id", "late"]]
    s = f["order_items"][["seller_id", "order_id"]].drop_duplicates().merge(d, on="order_id")
    g = s.groupby("seller_id").late.agg(["sum", "count"])
    g = g[g["count"] >= 30]
    g["rate"] = (100.0 * g["sum"] / g["count"]).round(2)
    g = g.reset_index().sort_values(["rate", "seller_id"], ascending=[False, True]).head(5)
    return list(zip(g.seller_id, g.rate, strict=True))


def trap_07(f):
    o = f["orders"]
    o = o[
        (o.order_purchase_timestamp >= "2018-01-01") & (o.order_purchase_timestamp < "2018-09-01")
    ]
    return [(round(o.groupby(months(o)).size().mean(), 2),)]


def trap_08(f):
    return [(int((latest_reviews(f).review_score == 1).sum()),)]


def trap_10(f):
    s = sale_items(f)
    nov = s[
        (s.order_purchase_timestamp >= "2017-11-01") & (s.order_purchase_timestamp < "2017-12-01")
    ]
    return [(nov.price.sum(),)]


def trap_11(f):
    s = sale_items(f)
    return [(s[s.order_purchase_timestamp < "2017-01-01"].price.sum(),)]


def trap_13(f):
    o = f["orders"].merge(f["customers"], on="customer_id")
    n = o.groupby("customer_unique_id").size()
    return [(rate(n > 1),)]


CHECKS: dict[str, Callable[[Frames], list[tuple]]] = {
    name: fn
    for name, fn in globals().items()
    if callable(fn)
    and name.split("_")[0] in {"lookup", "agg", "trend", "trap"}
    and name[-2:].isdigit()
}


def run(frames: Frames | None = None) -> list[tuple[str, bool, str]]:
    frames = frames or load_frames()
    items = {i.id: i for i in load_golden()}
    results = []
    with connect_eval() as conn:
        for item_id, fn in CHECKS.items():
            item = items[item_id]
            ref_rows = conn.execute(item.reference_sql).fetchall()
            cmp = compare_results(ref_rows, fn(frames), ordered=item.ordering == "ordered")
            results.append((item_id, cmp.match, cmp.reason))
    return results


def main() -> int:
    results = run()
    for item_id, match, reason in results:
        print(f"  {item_id:<10} {'agree' if match else 'DISAGREE: ' + reason}")
    agree = sum(m for _, m, _ in results)
    print(f"\n{agree} of {len(results)} references agree with the pandas implementation")
    return 0 if agree == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
