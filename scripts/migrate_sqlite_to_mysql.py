"""Load the local Olist SQLite snapshot into the Docker MySQL database.

The migration is idempotent: the SHA-256 of the source database is recorded,
so normal ``docker compose up`` does not import 100k orders again.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sqlite3
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pymysql
from pymysql.cursors import DictCursor

MIGRATION_NAME = "olist_sqlite_snapshot_v1"
OLIST_TABLES = [
    "olist_customers",
    "olist_products",
    "olist_sellers",
    "olist_orders",
    "olist_order_items",
    "olist_order_payments",
    "olist_order_reviews",
    "olist_support_tickets",
    "dataset_metadata",
]


def mysql_connection() -> pymysql.Connection:
    return pymysql.connect(
        host=os.getenv("MYSQL_HOST", "127.0.0.1"),
        port=int(os.getenv("MYSQL_PORT", "3306")),
        user=os.getenv("MYSQL_USER", "support_app"),
        password=os.getenv("MYSQL_PASSWORD", "support_dev_password"),
        database=os.getenv("MYSQL_DATABASE", "ecommerce_support"),
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=False,
        connect_timeout=15,
    )


def source_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def schema_statements() -> list[str]:
    return [
        """
        CREATE TABLE IF NOT EXISTS customers (
            id VARCHAR(32) PRIMARY KEY,
            name VARCHAR(100) NOT NULL,
            phone_last4 CHAR(4) NOT NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
        """
        CREATE TABLE IF NOT EXISTS orders (
            id VARCHAR(32) PRIMARY KEY,
            customer_id VARCHAR(32) NOT NULL,
            status VARCHAR(32) NOT NULL,
            product_name VARCHAR(255) NOT NULL,
            delivered_days_ago INTEGER NULL,
            item_condition VARCHAR(32) NOT NULL,
            CONSTRAINT fk_orders_customer
                FOREIGN KEY (customer_id) REFERENCES customers(id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
        """
        CREATE TABLE IF NOT EXISTS support_tickets (
            id VARCHAR(32) PRIMARY KEY,
            order_id VARCHAR(32) NOT NULL,
            category VARCHAR(100) NOT NULL,
            summary TEXT NOT NULL,
            status VARCHAR(32) NOT NULL,
            idempotency_key VARCHAR(255) NOT NULL UNIQUE,
            created_at VARCHAR(40) NOT NULL,
            INDEX idx_support_tickets_order (order_id),
            CONSTRAINT fk_support_ticket_order
                FOREIGN KEY (order_id) REFERENCES orders(id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
        """
        CREATE TABLE IF NOT EXISTS olist_customers (
            customer_id VARCHAR(64) PRIMARY KEY,
            customer_unique_id VARCHAR(64) NOT NULL,
            customer_zip_code_prefix INTEGER NULL,
            customer_city VARCHAR(100) NULL,
            customer_state VARCHAR(8) NULL,
            demo_phone_last4 CHAR(4) NOT NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
        """
        CREATE TABLE IF NOT EXISTS olist_orders (
            order_alias VARCHAR(16) PRIMARY KEY,
            source_order_id VARCHAR(64) NOT NULL UNIQUE,
            customer_id VARCHAR(64) NOT NULL,
            order_status VARCHAR(32) NOT NULL,
            status_zh VARCHAR(32) NOT NULL,
            order_purchase_timestamp VARCHAR(32) NULL,
            order_approved_at VARCHAR(32) NULL,
            order_delivered_carrier_date VARCHAR(32) NULL,
            order_delivered_customer_date VARCHAR(32) NULL,
            order_estimated_delivery_date VARCHAR(32) NULL,
            days_since_delivery INTEGER NULL,
            delivery_delay_days INTEGER NULL,
            is_delivery_late TINYINT NOT NULL,
            INDEX idx_olist_orders_customer (customer_id),
            INDEX idx_olist_orders_status (order_status),
            INDEX idx_olist_orders_late (is_delivery_late),
            CONSTRAINT fk_olist_orders_customer
                FOREIGN KEY (customer_id) REFERENCES olist_customers(customer_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
        """
        CREATE TABLE IF NOT EXISTS olist_products (
            product_id VARCHAR(64) PRIMARY KEY,
            product_category_name VARCHAR(100) NULL,
            product_name_lenght DOUBLE NULL,
            product_description_lenght DOUBLE NULL,
            product_photos_qty DOUBLE NULL,
            product_weight_g DOUBLE NULL,
            product_length_cm DOUBLE NULL,
            product_height_cm DOUBLE NULL,
            product_width_cm DOUBLE NULL,
            product_category_name_english VARCHAR(100) NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
        """
        CREATE TABLE IF NOT EXISTS olist_sellers (
            seller_id VARCHAR(64) PRIMARY KEY,
            seller_zip_code_prefix INTEGER NULL,
            seller_city VARCHAR(100) NULL,
            seller_state VARCHAR(8) NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
        """
        CREATE TABLE IF NOT EXISTS olist_order_items (
            order_item_id INTEGER NOT NULL,
            product_id VARCHAR(64) NULL,
            seller_id VARCHAR(64) NULL,
            shipping_limit_date VARCHAR(32) NULL,
            price DOUBLE NULL,
            freight_value DOUBLE NULL,
            order_alias VARCHAR(16) NOT NULL,
            PRIMARY KEY (order_alias, order_item_id),
            INDEX idx_olist_items_product (product_id),
            INDEX idx_olist_items_seller (seller_id),
            CONSTRAINT fk_olist_items_order
                FOREIGN KEY (order_alias) REFERENCES olist_orders(order_alias),
            CONSTRAINT fk_olist_items_product
                FOREIGN KEY (product_id) REFERENCES olist_products(product_id),
            CONSTRAINT fk_olist_items_seller
                FOREIGN KEY (seller_id) REFERENCES olist_sellers(seller_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
        """
        CREATE TABLE IF NOT EXISTS olist_order_payments (
            payment_sequential INTEGER NOT NULL,
            payment_type VARCHAR(32) NULL,
            payment_installments INTEGER NULL,
            payment_value DOUBLE NULL,
            order_alias VARCHAR(16) NOT NULL,
            PRIMARY KEY (order_alias, payment_sequential),
            INDEX idx_olist_payments_order (order_alias),
            CONSTRAINT fk_olist_payments_order
                FOREIGN KEY (order_alias) REFERENCES olist_orders(order_alias)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
        """
        CREATE TABLE IF NOT EXISTS olist_order_reviews (
            review_row_id INTEGER PRIMARY KEY,
            review_id VARCHAR(64) NULL,
            review_score INTEGER NULL,
            review_comment_title TEXT NULL,
            review_comment_message TEXT NULL,
            review_creation_date VARCHAR(32) NULL,
            review_answer_timestamp VARCHAR(32) NULL,
            order_alias VARCHAR(16) NOT NULL,
            INDEX idx_olist_reviews_order (order_alias),
            CONSTRAINT fk_olist_reviews_order
                FOREIGN KEY (order_alias) REFERENCES olist_orders(order_alias)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
        """
        CREATE TABLE IF NOT EXISTS olist_support_tickets (
            id VARCHAR(32) PRIMARY KEY,
            order_alias VARCHAR(16) NOT NULL,
            category VARCHAR(100) NOT NULL,
            summary TEXT NOT NULL,
            status VARCHAR(32) NOT NULL,
            idempotency_key VARCHAR(255) NOT NULL UNIQUE,
            created_at VARCHAR(40) NOT NULL,
            INDEX idx_olist_tickets_order (order_alias),
            CONSTRAINT fk_olist_ticket_order
                FOREIGN KEY (order_alias) REFERENCES olist_orders(order_alias)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
        """
        CREATE TABLE IF NOT EXISTS dataset_metadata (
            `key` VARCHAR(100) PRIMARY KEY,
            value TEXT NOT NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
        """
        CREATE TABLE IF NOT EXISTS migration_history (
            migration_name VARCHAR(100) PRIMARY KEY,
            source_sha256 CHAR(64) NOT NULL,
            completed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
    ]


def initialize_schema(connection: pymysql.Connection) -> None:
    with connection.cursor() as cursor:
        for statement in schema_statements():
            cursor.execute(statement)
        cursor.execute(
            """
            INSERT IGNORE INTO customers(id, name, phone_last4)
            VALUES ('C001', '演示用户', '8821')
            """
        )
        cursor.executemany(
            """
            INSERT IGNORE INTO orders(
                id, customer_id, status, product_name,
                delivered_days_ago, item_condition
            ) VALUES (%s, 'C001', %s, %s, %s, %s)
            """,
            [
                ("ORD1001", "运输中", "无线耳机", None, "未签收"),
                ("ORD1002", "已签收", "机械键盘", 3, "未拆封"),
                ("ORD1003", "已签收", "定制鼠标垫", 12, "已拆封"),
            ],
        )
    connection.commit()


def sqlite_columns(connection: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in connection.execute(f"PRAGMA table_info({table})")]


def row_batches(
    connection: sqlite3.Connection,
    table: str,
    batch_size: int,
) -> Iterator[list[tuple[Any, ...]]]:
    cursor = connection.execute(f"SELECT * FROM {table}")
    while rows := cursor.fetchmany(batch_size):
        yield [tuple(row) for row in rows]


def clear_olist_tables(connection: pymysql.Connection) -> None:
    with connection.cursor() as cursor:
        cursor.execute("SET FOREIGN_KEY_CHECKS = 0")
        for table in reversed(OLIST_TABLES):
            cursor.execute(f"TRUNCATE TABLE `{table}`")
        cursor.execute("SET FOREIGN_KEY_CHECKS = 1")
    connection.commit()


def copy_table(
    sqlite_connection: sqlite3.Connection,
    mysql_connection_: pymysql.Connection,
    table: str,
    batch_size: int,
) -> int:
    columns = sqlite_columns(sqlite_connection, table)
    quoted_columns = ", ".join(f"`{column}`" for column in columns)
    placeholders = ", ".join(["%s"] * len(columns))
    insert_sql = f"INSERT INTO `{table}` ({quoted_columns}) VALUES ({placeholders})"
    copied = 0
    with mysql_connection_.cursor() as cursor:
        for batch in row_batches(sqlite_connection, table, batch_size):
            cursor.executemany(insert_sql, batch)
            mysql_connection_.commit()
            copied += len(batch)
            print(f"  {table}: {copied:,} rows", flush=True)
    return copied


def migrate(source: Path, force: bool, batch_size: int) -> None:
    if not source.exists():
        raise FileNotFoundError(
            f"Source database not found: {source}. Run scripts/import_olist.py first."
        )
    fingerprint = source_sha256(source)

    with mysql_connection() as destination:
        initialize_schema(destination)
        with destination.cursor() as cursor:
            cursor.execute(
                """
                SELECT source_sha256
                FROM migration_history
                WHERE migration_name = %s
                """,
                (MIGRATION_NAME,),
            )
            previous = cursor.fetchone()
        if previous and previous["source_sha256"] == fingerprint and not force:
            print("MySQL already contains this Olist snapshot; migration skipped.")
            return
        if previous and previous["source_sha256"] != fingerprint and not force:
            raise RuntimeError(
                "The SQLite snapshot changed. Re-run with --force to replace Olist tables."
            )

        clear_olist_tables(destination)
        with sqlite3.connect(source) as origin:
            for table in OLIST_TABLES:
                copy_table(origin, destination, table, batch_size)

        with destination.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO migration_history(migration_name, source_sha256)
                VALUES (%s, %s)
                ON DUPLICATE KEY UPDATE
                    source_sha256 = VALUES(source_sha256),
                    completed_at = CURRENT_TIMESTAMP
                """,
                (MIGRATION_NAME, fingerprint),
            )
        destination.commit()
    print("MySQL migration completed successfully.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source",
        type=Path,
        default=Path("data/olist_support.db"),
        help="Path to the generated Olist SQLite database.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace existing Olist tables even if a migration was recorded.",
    )
    parser.add_argument("--batch-size", type=int, default=2000)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        migrate(args.source, args.force, args.batch_size)
    except Exception as error:
        print(f"Migration failed: {error}", file=sys.stderr)
        raise


if __name__ == "__main__":
    main()
