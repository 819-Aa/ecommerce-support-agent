"""Import the anonymized Olist ecommerce CSV dataset into a local SQLite database."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

DEFAULT_SOURCE = PROJECT_ROOT / "data" / "raw" / "olist"
DEFAULT_DATABASE = PROJECT_ROOT / "data" / "olist_support.db"
DEFAULT_REPORT = PROJECT_ROOT / "data" / "evaluation" / "olist_import_report.json"

STATUS_ZH = {
    "created": "已创建",
    "approved": "已付款",
    "invoiced": "已开票",
    "processing": "处理中",
    "shipped": "运输中",
    "delivered": "已签收",
    "unavailable": "商品缺货",
    "canceled": "已取消",
}

REQUIRED_FILES = {
    "customers": "olist_customers_dataset.csv",
    "orders": "olist_orders_dataset.csv",
    "items": "olist_order_items_dataset.csv",
    "payments": "olist_order_payments_dataset.csv",
    "reviews": "olist_order_reviews_dataset.csv",
    "products": "olist_products_dataset.csv",
    "sellers": "olist_sellers_dataset.csv",
    "translations": "product_category_name_translation.csv",
}


def _phone_last4(customer_unique_id: str) -> str:
    """Create a stable demo credential from an already-anonymized customer id."""
    digest = hashlib.sha256(customer_unique_id.encode()).hexdigest()
    return f"{int(digest[:8], 16) % 10000:04d}"


def _read_csvs(source: Path) -> dict[str, pd.DataFrame]:
    missing = [filename for filename in REQUIRED_FILES.values() if not (source / filename).exists()]
    if missing:
        raise FileNotFoundError(f"缺少Olist文件：{', '.join(missing)}")
    return {
        name: pd.read_csv(source / filename, low_memory=False)
        for name, filename in REQUIRED_FILES.items()
    }


def _prepare_frames(
    frames: dict[str, pd.DataFrame],
    limit: int | None,
) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
    orders = frames["orders"].copy()
    orders = orders.sort_values(["order_purchase_timestamp", "order_id"]).reset_index(drop=True)
    if limit is not None:
        orders = orders.head(limit).copy()

    orders["order_alias"] = [f"OL{index:06d}" for index in range(1, len(orders) + 1)]
    order_aliases = orders[["order_id", "order_alias"]].copy()
    selected_order_ids = set(orders["order_id"])

    purchase_dates = pd.to_datetime(orders["order_purchase_timestamp"], errors="coerce")
    delivered_dates = pd.to_datetime(orders["order_delivered_customer_date"], errors="coerce")
    estimated_dates = pd.to_datetime(orders["order_estimated_delivery_date"], errors="coerce")
    snapshot_date = purchase_dates.max()
    if pd.isna(snapshot_date):
        raise ValueError("订单数据没有有效的购买时间")

    days_since_delivery = (snapshot_date - delivered_dates).dt.days
    orders["days_since_delivery"] = days_since_delivery.where(days_since_delivery >= 0).astype(
        "Int64"
    )
    delivery_delay_days = (delivered_dates - estimated_dates).dt.days
    orders["delivery_delay_days"] = delivery_delay_days.astype("Int64")
    undelivered_late = (
        delivered_dates.isna()
        & estimated_dates.notna()
        & (estimated_dates < snapshot_date)
        & ~orders["order_status"].isin(["canceled", "unavailable"])
    )
    orders["is_delivery_late"] = ((delivery_delay_days > 0) | undelivered_late).astype(int)
    orders["status_zh"] = orders["order_status"].map(STATUS_ZH).fillna(orders["order_status"])
    orders = orders.rename(columns={"order_id": "source_order_id"})
    orders = orders[
        [
            "order_alias",
            "source_order_id",
            "customer_id",
            "order_status",
            "status_zh",
            "order_purchase_timestamp",
            "order_approved_at",
            "order_delivered_carrier_date",
            "order_delivered_customer_date",
            "order_estimated_delivery_date",
            "days_since_delivery",
            "delivery_delay_days",
            "is_delivery_late",
        ]
    ]

    customer_ids = set(orders["customer_id"])
    customers = frames["customers"][frames["customers"]["customer_id"].isin(customer_ids)].copy()
    customers["demo_phone_last4"] = customers["customer_unique_id"].map(_phone_last4)

    items = frames["items"][frames["items"]["order_id"].isin(selected_order_ids)].merge(
        order_aliases, on="order_id", how="inner"
    )
    items = items.drop(columns=["order_id"])
    product_ids = set(items["product_id"].dropna())
    seller_ids = set(items["seller_id"].dropna())

    products = frames["products"][frames["products"]["product_id"].isin(product_ids)].copy()
    products = products.merge(
        frames["translations"],
        on="product_category_name",
        how="left",
    )

    sellers = frames["sellers"][frames["sellers"]["seller_id"].isin(seller_ids)].copy()

    payments = frames["payments"][frames["payments"]["order_id"].isin(selected_order_ids)].merge(
        order_aliases, on="order_id", how="inner"
    )
    payments = payments.drop(columns=["order_id"])

    reviews = frames["reviews"][frames["reviews"]["order_id"].isin(selected_order_ids)].merge(
        order_aliases, on="order_id", how="inner"
    )
    reviews = reviews.drop(columns=["order_id"]).reset_index(drop=True)
    reviews.insert(0, "review_row_id", range(1, len(reviews) + 1))

    prepared = {
        "olist_customers": customers,
        "olist_orders": orders,
        "olist_order_items": items,
        "olist_products": products,
        "olist_sellers": sellers,
        "olist_order_payments": payments,
        "olist_order_reviews": reviews,
    }
    metadata = {
        "source": "Brazilian E-Commerce Public Dataset by Olist",
        "license": "CC BY-NC-SA 4.0",
        "snapshot_date": snapshot_date.isoformat(),
        "order_count": len(orders),
        "generated_phone_note": (
            "demo_phone_last4 is deterministically derived from anonymized "
            "customer_unique_id; it is not a real phone number"
        ),
    }
    return prepared, metadata


def _create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE olist_customers (
            customer_id TEXT PRIMARY KEY,
            customer_unique_id TEXT NOT NULL,
            customer_zip_code_prefix INTEGER,
            customer_city TEXT,
            customer_state TEXT,
            demo_phone_last4 TEXT NOT NULL
        );

        CREATE TABLE olist_orders (
            order_alias TEXT PRIMARY KEY,
            source_order_id TEXT NOT NULL UNIQUE,
            customer_id TEXT NOT NULL REFERENCES olist_customers(customer_id),
            order_status TEXT NOT NULL,
            status_zh TEXT NOT NULL,
            order_purchase_timestamp TEXT,
            order_approved_at TEXT,
            order_delivered_carrier_date TEXT,
            order_delivered_customer_date TEXT,
            order_estimated_delivery_date TEXT,
            days_since_delivery INTEGER,
            delivery_delay_days INTEGER,
            is_delivery_late INTEGER NOT NULL
        );

        CREATE TABLE olist_order_items (
            order_item_id INTEGER NOT NULL,
            product_id TEXT,
            seller_id TEXT,
            shipping_limit_date TEXT,
            price REAL,
            freight_value REAL,
            order_alias TEXT NOT NULL REFERENCES olist_orders(order_alias),
            PRIMARY KEY (order_alias, order_item_id)
        );

        CREATE TABLE olist_products (
            product_id TEXT PRIMARY KEY,
            product_category_name TEXT,
            product_name_lenght REAL,
            product_description_lenght REAL,
            product_photos_qty REAL,
            product_weight_g REAL,
            product_length_cm REAL,
            product_height_cm REAL,
            product_width_cm REAL,
            product_category_name_english TEXT
        );

        CREATE TABLE olist_sellers (
            seller_id TEXT PRIMARY KEY,
            seller_zip_code_prefix INTEGER,
            seller_city TEXT,
            seller_state TEXT
        );

        CREATE TABLE olist_order_payments (
            payment_sequential INTEGER NOT NULL,
            payment_type TEXT,
            payment_installments INTEGER,
            payment_value REAL,
            order_alias TEXT NOT NULL REFERENCES olist_orders(order_alias),
            PRIMARY KEY (order_alias, payment_sequential)
        );

        CREATE TABLE olist_order_reviews (
            review_row_id INTEGER PRIMARY KEY,
            review_id TEXT,
            review_score INTEGER,
            review_comment_title TEXT,
            review_comment_message TEXT,
            review_creation_date TEXT,
            review_answer_timestamp TEXT,
            order_alias TEXT NOT NULL REFERENCES olist_orders(order_alias)
        );

        CREATE TABLE olist_support_tickets (
            id TEXT PRIMARY KEY,
            order_alias TEXT NOT NULL REFERENCES olist_orders(order_alias),
            category TEXT NOT NULL,
            summary TEXT NOT NULL,
            status TEXT NOT NULL,
            idempotency_key TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL
        );

        CREATE TABLE dataset_metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """
    )


def _write_database(
    database: Path,
    prepared: dict[str, pd.DataFrame],
    metadata: dict[str, Any],
) -> None:
    temporary = database.with_suffix(".tmp.db")
    temporary.unlink(missing_ok=True)
    database.parent.mkdir(parents=True, exist_ok=True)

    try:
        connection = sqlite3.connect(temporary)
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            _create_schema(connection)
            for table, frame in prepared.items():
                frame.to_sql(
                    table,
                    connection,
                    if_exists="append",
                    index=False,
                    chunksize=1000,
                )
            connection.executemany(
                "INSERT INTO dataset_metadata(key, value) VALUES (?, ?)",
                [(key, json.dumps(value, ensure_ascii=False)) for key, value in metadata.items()],
            )
            connection.executescript(
                """
                CREATE INDEX idx_olist_orders_customer
                    ON olist_orders(customer_id);
                CREATE INDEX idx_olist_orders_status
                    ON olist_orders(order_status);
                CREATE INDEX idx_olist_orders_late
                    ON olist_orders(is_delivery_late);
                CREATE INDEX idx_olist_items_product
                    ON olist_order_items(product_id);
                CREATE INDEX idx_olist_payments_order
                    ON olist_order_payments(order_alias);
                CREATE INDEX idx_olist_reviews_order
                    ON olist_order_reviews(order_alias);
                """
            )
            connection.commit()
        finally:
            connection.close()
        temporary.replace(database)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _quality_report(
    database: Path,
    prepared: dict[str, pd.DataFrame],
) -> dict[str, Any]:
    with sqlite3.connect(database) as connection:
        counts = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in prepared
        }
        orphan_items = connection.execute(
            """
            SELECT COUNT(*)
            FROM olist_order_items AS i
            LEFT JOIN olist_orders AS o ON o.order_alias = i.order_alias
            WHERE o.order_alias IS NULL
            """
        ).fetchone()[0]
        duplicate_aliases = connection.execute(
            """
            SELECT COUNT(*) FROM (
                SELECT order_alias
                FROM olist_orders
                GROUP BY order_alias
                HAVING COUNT(*) > 1
            )
            """
        ).fetchone()[0]
        demo_orders = connection.execute(
            """
            SELECT
                o.order_alias,
                c.demo_phone_last4,
                o.status_zh,
                COALESCE(p.product_category_name_english, p.product_category_name)
            FROM olist_orders AS o
            JOIN olist_customers AS c ON c.customer_id = o.customer_id
            LEFT JOIN olist_order_items AS i ON i.order_alias = o.order_alias
            LEFT JOIN olist_products AS p ON p.product_id = i.product_id
            WHERE o.order_status IN ('delivered', 'shipped')
            ORDER BY o.order_purchase_timestamp DESC
            LIMIT 5
            """
        ).fetchall()

    return {
        "counts": counts,
        "orphan_items": orphan_items,
        "duplicate_aliases": duplicate_aliases,
        "demo_orders": demo_orders,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    source = args.source.resolve()
    database = args.database.resolve()
    if args.limit is not None and args.limit <= 0:
        raise ValueError("--limit must be greater than zero")
    if database.exists() and not args.force:
        raise FileExistsError(f"{database} 已存在；确认重建时使用 --force")

    print(f"读取原始数据：{source}")
    frames = _read_csvs(source)
    prepared, metadata = _prepare_frames(frames, args.limit)
    _write_database(database, prepared, metadata)
    report = _quality_report(database, prepared)
    report["metadata"] = metadata
    report["database_size_mb"] = round(database.stat().st_size / 1024 / 1024, 2)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"数据库已生成：{database}")
    print(f"数据库大小：{database.stat().st_size / 1024 / 1024:.1f} MB")
    print("导入行数：")
    for table, count in report["counts"].items():
        print(f"  {table}: {count:,}")
    print(
        f"质量检查：孤儿明细={report['orphan_items']}，重复订单别名={report['duplicate_aliases']}"
    )
    print("可用于客服演示的订单：")
    for alias, phone_last4, status, category in report["demo_orders"]:
        print(f"  {alias} / 手机后四位 {phone_last4} / {status} / {category}")
    print(f"导入报告：{args.report.resolve()}")


if __name__ == "__main__":
    main()
