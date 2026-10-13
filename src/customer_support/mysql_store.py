"""MySQL implementation of the customer-support business data store."""

from __future__ import annotations

import os
import re
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import pymysql
from pymysql.cursors import DictCursor

DISPLAY_TIMEZONE = ZoneInfo("Asia/Shanghai")
TICKET_TABLES = {"support_tickets", "olist_support_tickets"}


def _created_at_for_display(value: Any) -> Any:
    """Convert stored UTC ticket timestamps to a Beijing-time display string.

    Older rows contain a timezone-naive UTC string; newer rows contain an
    explicit ``+00:00`` offset. Non-date values are returned unchanged so the
    read-only browser remains resilient to imported data.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        timestamp = value
    else:
        raw_value = str(value).strip()
        if raw_value.endswith("Z"):
            raw_value = f"{raw_value[:-1]}+00:00"
        try:
            timestamp = datetime.fromisoformat(raw_value)
        except ValueError:
            return value

    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    return timestamp.astimezone(DISPLAY_TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")


def _connect() -> pymysql.Connection:
    """Open a short-lived connection using Docker-friendly environment variables."""
    return pymysql.connect(
        host=os.getenv("MYSQL_HOST", "127.0.0.1"),
        port=int(os.getenv("MYSQL_PORT", "3306")),
        user=os.getenv("MYSQL_USER", "support_app"),
        password=os.getenv("MYSQL_PASSWORD", "support_dev_password"),
        database=os.getenv("MYSQL_DATABASE", "ecommerce_support"),
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=False,
        connect_timeout=10,
    )


def _is_olist_order(order_id: str) -> bool:
    from customer_support.olist_store import is_olist_order_id

    return is_olist_order_id(order_id)


def _get_demo_order(order_id: str, phone_last4: str) -> dict[str, Any]:
    with _connect() as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT o.*, c.phone_last4
            FROM orders AS o
            JOIN customers AS c ON c.id = o.customer_id
            WHERE o.id = %s AND c.phone_last4 = %s
            """,
            (order_id.upper(), phone_last4),
        )
        row = cursor.fetchone()
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
        "data_source": "MySQL 演示业务数据",
    }


def _get_olist_order(order_id: str, phone_last4: str) -> dict[str, Any]:
    alias = order_id.strip().upper()
    with _connect() as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            WITH item_summary AS (
                SELECT
                    i.order_alias,
                    GROUP_CONCAT(
                        DISTINCT COALESCE(
                            p.product_category_name_english,
                            p.product_category_name,
                            'unknown'
                        )
                    ) AS product_categories,
                    ROUND(SUM(i.price), 2) AS item_total,
                    ROUND(SUM(i.freight_value), 2) AS freight_total,
                    COUNT(*) AS item_count
                FROM olist_order_items AS i
                LEFT JOIN olist_products AS p ON p.product_id = i.product_id
                WHERE i.order_alias = %s
                GROUP BY i.order_alias
            ),
            payment_summary AS (
                SELECT
                    order_alias,
                    ROUND(SUM(payment_value), 2) AS payment_total,
                    GROUP_CONCAT(DISTINCT payment_type) AS payment_types
                FROM olist_order_payments
                WHERE order_alias = %s
                GROUP BY order_alias
            ),
            review_summary AS (
                SELECT order_alias, ROUND(AVG(review_score), 2) AS review_score
                FROM olist_order_reviews
                WHERE order_alias = %s
                GROUP BY order_alias
            )
            SELECT
                o.*,
                c.demo_phone_last4,
                c.customer_city,
                c.customer_state,
                i.product_categories,
                i.item_total,
                i.freight_total,
                i.item_count,
                p.payment_total,
                p.payment_types,
                r.review_score
            FROM olist_orders AS o
            JOIN olist_customers AS c ON c.customer_id = o.customer_id
            LEFT JOIN item_summary AS i ON i.order_alias = o.order_alias
            LEFT JOIN payment_summary AS p ON p.order_alias = o.order_alias
            LEFT JOIN review_summary AS r ON r.order_alias = o.order_alias
            WHERE o.order_alias = %s
              AND LPAD(CAST(c.demo_phone_last4 AS CHAR), 4, '0') = %s
            """,
            (alias, alias, alias, alias, phone_last4),
        )
        row = cursor.fetchone()

    if row is None:
        return {
            "ok": False,
            "error": "未找到订单或验证信息不匹配。",
            "error_code": "ORDER_NOT_FOUND_OR_VERIFICATION_FAILED",
        }

    categories = (row["product_categories"] or "unknown").replace("_", " ")
    return {
        "ok": True,
        "order_id": row["order_alias"],
        "status": row["status_zh"],
        "product_name": categories,
        "item_count": row["item_count"],
        "item_total": float(row["item_total"]) if row["item_total"] is not None else None,
        "freight_total": (
            float(row["freight_total"]) if row["freight_total"] is not None else None
        ),
        "payment_total": (
            float(row["payment_total"]) if row["payment_total"] is not None else None
        ),
        "payment_types": row["payment_types"],
        "purchase_at": row["order_purchase_timestamp"],
        "delivered_at": row["order_delivered_customer_date"],
        "estimated_delivery_at": row["order_estimated_delivery_date"],
        "delivered_days_ago": row["days_since_delivery"],
        "delivery_delay_days": row["delivery_delay_days"],
        "is_delivery_late": bool(row["is_delivery_late"]),
        "item_condition": "未知（原始数据集未提供）",
        "customer_location": f"{row['customer_city']}, {row['customer_state']}",
        "review_score": (float(row["review_score"]) if row["review_score"] is not None else None),
        "data_source": "MySQL 中的 Olist 匿名公开电商数据",
    }


def get_order_status(order_id: str, phone_last4: str) -> dict[str, Any]:
    """Query either the small deterministic order set or an Olist order."""
    if _is_olist_order(order_id):
        return _get_olist_order(order_id, phone_last4)
    return _get_demo_order(order_id, phone_last4)


def database_healthcheck() -> dict[str, Any]:
    """Verify that MySQL is reachable and the migrated order table is queryable."""
    with _connect() as connection, connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) AS order_count FROM olist_orders")
        result = cursor.fetchone()
    return {
        "status": "ready",
        "backend": "mysql",
        "order_count": result["order_count"],
    }


def list_database_tables() -> list[str]:
    """List business tables for the local read-only learning page."""
    with _connect() as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = %s
            ORDER BY table_name
            """,
            (os.getenv("MYSQL_DATABASE", "ecommerce_support"),),
        )
        return [row["TABLE_NAME"] for row in cursor.fetchall()]


def browse_database_table(
    table: str,
    limit: int = 20,
    offset: int = 0,
    order_alias: str | None = None,
) -> dict[str, Any]:
    """Return one safe page without accepting arbitrary SQL from the browser."""
    if not re.fullmatch(r"[a-zA-Z0-9_]+", table):
        raise ValueError("Invalid table name")
    if table not in list_database_tables():
        raise ValueError("Unknown table")
    limit = max(1, min(limit, 100))
    offset = max(0, offset)

    with _connect() as connection, connection.cursor() as cursor:
        cursor.execute(f"SELECT COUNT(*) AS count FROM `{table}`")
        total = int(cursor.fetchone()["count"])
        if table == "olist_orders" and order_alias:
            cursor.execute(
                "SELECT * FROM olist_orders WHERE order_alias = %s",
                (order_alias.strip().upper(),),
            )
        else:
            cursor.execute(
                f"SELECT * FROM `{table}` LIMIT %s OFFSET %s",
                (limit, offset),
            )
        rows = list(cursor.fetchall())
    if table in TICKET_TABLES:
        rows = [
            {**row, "created_at": _created_at_for_display(row.get("created_at"))} for row in rows
        ]
    return {"table": table, "total": total, "rows": rows}


def refund_eligibility(order_id: str, phone_last4: str) -> dict[str, Any]:
    """Apply the seven-day demo rule without inventing missing Olist fields."""
    order = get_order_status(order_id, phone_last4)
    if not order["ok"]:
        return order
    if order["status"] != "已签收":
        return {
            "ok": True,
            "eligible": False,
            "requires_manual_review": False,
            "reason": "订单尚未签收，不满足签收后七天退款判断条件。",
            "order": order,
        }
    days = order["delivered_days_ago"]
    if days is None or days > 7:
        return {
            "ok": True,
            "eligible": False,
            "requires_manual_review": False,
            "reason": "订单已超过签收后七天的退款时限。",
            "order": order,
        }
    if _is_olist_order(order_id):
        return {
            "ok": True,
            "eligible": None,
            "requires_manual_review": True,
            "reason": (
                "订单在七天时间窗口内，但 Olist 原始数据没有商品是否拆封字段，"
                "需要人工审核商品状态后才能确定。"
            ),
            "order": order,
        }
    if order["item_condition"] != "未拆封":
        return {
            "ok": True,
            "eligible": False,
            "requires_manual_review": False,
            "reason": "商品已拆封或影响二次销售，不符合演示退款规则。",
            "order": order,
        }
    return {
        "ok": True,
        "eligible": True,
        "requires_manual_review": False,
        "reason": "订单在签收后七天内且商品未拆封，符合演示退款规则。",
        "order": order,
    }


def create_support_ticket(
    order_id: str,
    category: str,
    summary: str,
    idempotency_key: str,
) -> dict[str, Any]:
    """Create a ticket atomically; a repeated idempotency key returns the old ticket."""
    is_olist = _is_olist_order(order_id)
    ticket_table = "olist_support_tickets" if is_olist else "support_tickets"
    order_table = "olist_orders" if is_olist else "orders"
    order_column = "order_alias" if is_olist else "id"
    ticket_order_column = "order_alias" if is_olist else "order_id"
    order_id = order_id.strip().upper()

    with _connect() as connection, connection.cursor() as cursor:
        cursor.execute(
            f"SELECT id, status FROM {ticket_table} WHERE idempotency_key = %s",
            (idempotency_key,),
        )
        existing = cursor.fetchone()
        if existing:
            return {
                "ok": True,
                "ticket_id": existing["id"],
                "status": existing["status"],
                "duplicate": True,
            }

        cursor.execute(
            f"SELECT {order_column} FROM {order_table} WHERE {order_column} = %s",
            (order_id,),
        )
        if cursor.fetchone() is None:
            return {"ok": False, "error": "未找到该订单，无法创建工单。"}

        prefix = "OTK" if is_olist else "TKT"
        ticket_id = f"{prefix}-{uuid4().hex[:8].upper()}"
        try:
            cursor.execute(
                f"""
                INSERT INTO {ticket_table}(
                    id, {ticket_order_column}, category, summary,
                    status, idempotency_key, created_at
                ) VALUES (%s, %s, %s, %s, '待处理', %s, %s)
                """,
                (
                    ticket_id,
                    order_id,
                    category,
                    summary,
                    idempotency_key,
                    datetime.now(UTC).isoformat(),
                ),
            )
            connection.commit()
        except pymysql.err.IntegrityError:
            connection.rollback()
            cursor.execute(
                f"SELECT id, status FROM {ticket_table} WHERE idempotency_key = %s",
                (idempotency_key,),
            )
            existing = cursor.fetchone()
            if existing:
                return {
                    "ok": True,
                    "ticket_id": existing["id"],
                    "status": existing["status"],
                    "duplicate": True,
                }
            raise

    return {
        "ok": True,
        "ticket_id": ticket_id,
        "status": "待处理",
        "duplicate": False,
    }
