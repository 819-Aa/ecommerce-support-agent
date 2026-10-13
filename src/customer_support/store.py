"""Small SQLite business database for the first runnable demo.

The production iteration will move the same schema behind SQLAlchemy/MySQL.
Keeping this first version in the Python standard library makes the business
flow testable before Docker or external services are introduced.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

DEFAULT_DB_PATH = Path(os.getenv("CUSTOMER_SUPPORT_DB_PATH", "data/customer_support.db"))


def _use_mysql(db_path: str | Path | None = None) -> bool:
    """Use MySQL in Docker, while explicit test database paths stay on SQLite."""
    return db_path is None and os.getenv("BUSINESS_DATABASE_TYPE", "sqlite").lower() == "mysql"


def _connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    path = Path(db_path or DEFAULT_DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database(db_path: str | Path | None = None) -> Path:
    """Create the demo schema and insert deterministic seed data."""
    path = Path(db_path or DEFAULT_DB_PATH)
    with closing(_connect(path)) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS customers (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                phone_last4 TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS orders (
                id TEXT PRIMARY KEY,
                customer_id TEXT NOT NULL REFERENCES customers(id),
                status TEXT NOT NULL,
                product_name TEXT NOT NULL,
                delivered_days_ago INTEGER,
                item_condition TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS support_tickets (
                id TEXT PRIMARY KEY,
                order_id TEXT NOT NULL REFERENCES orders(id),
                category TEXT NOT NULL,
                summary TEXT NOT NULL,
                status TEXT NOT NULL,
                idempotency_key TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL
            );
            """
        )
        connection.execute(
            """
            INSERT OR IGNORE INTO customers(id, name, phone_last4)
            VALUES ('C001', '演示用户', '8821')
            """
        )
        connection.executemany(
            """
            INSERT OR IGNORE INTO orders(
                id, customer_id, status, product_name, delivered_days_ago, item_condition
            ) VALUES (?, 'C001', ?, ?, ?, ?)
            """,
            [
                ("ORD1001", "运输中", "无线耳机", None, "未签收"),
                ("ORD1002", "已签收", "机械键盘", 3, "未拆封"),
                ("ORD1003", "已签收", "定制鼠标垫", 12, "已拆封"),
            ],
        )
        connection.commit()
    return path


def get_order_status(
    order_id: str,
    phone_last4: str,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Return an order only after the simple demo identity check succeeds."""
    if _use_mysql(db_path):
        from customer_support.mysql_store import get_order_status as get_mysql_order

        return get_mysql_order(order_id, phone_last4)

    from customer_support.olist_store import (
        get_olist_order_status,
        is_olist_order_id,
    )

    if is_olist_order_id(order_id):
        return get_olist_order_status(order_id, phone_last4)

    initialize_database(db_path)
    with closing(_connect(db_path)) as connection:
        row = connection.execute(
            """
            SELECT o.*, c.phone_last4
            FROM orders AS o
            JOIN customers AS c ON c.id = o.customer_id
            WHERE o.id = ? AND c.phone_last4 = ?
            """,
            (order_id.upper(), phone_last4),
        ).fetchone()
    if row is None:
        return {
            "ok": False,
            "error": "未找到订单或验证信息不匹配。",
            "error_code": "ORDER_NOT_FOUND_OR_VERIFICATION_FAILED",
        }
    return {
        "ok": True,
        "order_id": row["id"],
        "status": row["status"],
        "product_name": row["product_name"],
        "delivered_days_ago": row["delivered_days_ago"],
        "item_condition": row["item_condition"],
    }


def refund_eligibility(
    order_id: str,
    phone_last4: str,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Evaluate the intentionally simple seven-day demo policy."""
    if _use_mysql(db_path):
        from customer_support.mysql_store import refund_eligibility as mysql_refund_eligibility

        return mysql_refund_eligibility(order_id, phone_last4)

    from customer_support.olist_store import (
        is_olist_order_id,
        olist_refund_eligibility,
    )

    if is_olist_order_id(order_id):
        return olist_refund_eligibility(order_id, phone_last4)

    order = get_order_status(order_id, phone_last4, db_path)
    if not order["ok"]:
        return order
    if order["status"] != "已签收":
        return {
            "ok": True,
            "eligible": False,
            "reason": "订单尚未签收，请先处理物流问题，暂不能发起退货退款。",
            "order": order,
        }
    if order["delivered_days_ago"] is None or order["delivered_days_ago"] > 7:
        return {
            "ok": True,
            "eligible": False,
            "reason": "订单已超过签收后 7 天的无理由退货期限。",
            "order": order,
        }
    if order["item_condition"] != "未拆封":
        return {
            "ok": True,
            "eligible": False,
            "reason": "商品已拆封或影响二次销售，不符合演示退款规则。",
            "order": order,
        }
    return {
        "ok": True,
        "eligible": True,
        "reason": "订单在签收后 7 天内且商品未拆封，符合演示退款规则。",
        "order": order,
    }


def create_support_ticket(
    order_id: str,
    category: str,
    summary: str,
    idempotency_key: str,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Create one ticket per idempotency key."""
    if _use_mysql(db_path):
        from customer_support.mysql_store import create_support_ticket as create_mysql_ticket

        return create_mysql_ticket(
            order_id=order_id,
            category=category,
            summary=summary,
            idempotency_key=idempotency_key,
        )

    from customer_support.olist_store import (
        create_olist_support_ticket,
        is_olist_order_id,
    )

    if is_olist_order_id(order_id):
        return create_olist_support_ticket(
            order_id=order_id,
            category=category,
            summary=summary,
            idempotency_key=idempotency_key,
        )

    initialize_database(db_path)
    with closing(_connect(db_path)) as connection:
        existing = connection.execute(
            "SELECT id, status FROM support_tickets WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
        if existing:
            return {
                "ok": True,
                "ticket_id": existing["id"],
                "status": existing["status"],
                "duplicate": True,
            }
        order = connection.execute(
            "SELECT id FROM orders WHERE id = ?",
            (order_id.upper(),),
        ).fetchone()
        if order is None:
            return {"ok": False, "error": "未找到该订单，无法创建工单。"}
        ticket_id = f"TKT-{uuid4().hex[:8].upper()}"
        connection.execute(
            """
            INSERT INTO support_tickets(
                id, order_id, category, summary, status, idempotency_key, created_at
            ) VALUES (?, ?, ?, ?, '待处理', ?, ?)
            """,
            (
                ticket_id,
                order_id.upper(),
                category,
                summary,
                idempotency_key,
                datetime.now(UTC).isoformat(),
            ),
        )
        connection.commit()
    return {
        "ok": True,
        "ticket_id": ticket_id,
        "status": "待处理",
        "duplicate": False,
    }
