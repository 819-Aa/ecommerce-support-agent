"""Queries over the imported anonymized Olist ecommerce database."""

from __future__ import annotations

import os
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

DEFAULT_OLIST_DB_PATH = Path(os.getenv("OLIST_DB_PATH", "data/olist_support.db"))
OLIST_ORDER_PATTERN = re.compile(r"^OL\d{6}$", re.IGNORECASE)


def is_olist_order_id(order_id: str) -> bool:
    return bool(OLIST_ORDER_PATTERN.fullmatch(order_id.strip()))


def _connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    path = Path(db_path or DEFAULT_OLIST_DB_PATH)
    if not path.exists():
        raise FileNotFoundError(f"Olist数据库不存在：{path}。请先运行 scripts/import_olist.py。")
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def get_olist_order_status(
    order_id: str,
    phone_last4: str,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Return an anonymized Olist order after project identity verification."""
    alias = order_id.strip().upper()
    try:
        connection = _connect(db_path)
    except FileNotFoundError as error:
        return {"ok": False, "error": str(error)}

    try:
        row = connection.execute(
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
                WHERE i.order_alias = ?
                GROUP BY i.order_alias
            ),
            payment_summary AS (
                SELECT
                    order_alias,
                    ROUND(SUM(payment_value), 2) AS payment_total,
                    GROUP_CONCAT(DISTINCT payment_type) AS payment_types
                FROM olist_order_payments
                WHERE order_alias = ?
                GROUP BY order_alias
            ),
            review_summary AS (
                SELECT
                    order_alias,
                    ROUND(AVG(review_score), 2) AS review_score
                FROM olist_order_reviews
                WHERE order_alias = ?
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
            WHERE o.order_alias = ?
              AND printf('%04d', c.demo_phone_last4) = ?
            """,
            (alias, alias, alias, alias, phone_last4),
        ).fetchone()
    finally:
        connection.close()

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
        "item_total": row["item_total"],
        "freight_total": row["freight_total"],
        "payment_total": row["payment_total"],
        "payment_types": row["payment_types"],
        "purchase_at": row["order_purchase_timestamp"],
        "delivered_at": row["order_delivered_customer_date"],
        "estimated_delivery_at": row["order_estimated_delivery_date"],
        "delivered_days_ago": row["days_since_delivery"],
        "delivery_delay_days": row["delivery_delay_days"],
        "is_delivery_late": bool(row["is_delivery_late"]),
        "item_condition": "未知（原始数据集未提供）",
        "customer_location": f"{row['customer_city']}, {row['customer_state']}",
        "review_score": row["review_score"],
        "data_source": "Olist匿名公开电商数据",
    }


def olist_refund_eligibility(
    order_id: str,
    phone_last4: str,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Evaluate only what the Olist fields can support without inventing data."""
    order = get_olist_order_status(order_id, phone_last4, db_path)
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
            "reason": "以数据集快照日计算，订单已超过签收后七天。",
            "order": order,
        }
    return {
        "ok": True,
        "eligible": None,
        "requires_manual_review": True,
        "reason": (
            "订单在七天时间窗口内，但Olist原始数据没有商品是否拆封字段，"
            "需要人工审核商品状态后才能确定。"
        ),
        "order": order,
    }


def create_olist_support_ticket(
    order_id: str,
    category: str,
    summary: str,
    idempotency_key: str,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Create an idempotent demo ticket linked to an imported Olist order."""
    alias = order_id.strip().upper()
    try:
        connection = _connect(db_path)
    except FileNotFoundError as error:
        return {"ok": False, "error": str(error)}

    try:
        existing = connection.execute(
            """
            SELECT id, status
            FROM olist_support_tickets
            WHERE idempotency_key = ?
            """,
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
            "SELECT order_alias FROM olist_orders WHERE order_alias = ?",
            (alias,),
        ).fetchone()
        if order is None:
            return {"ok": False, "error": "未找到该Olist订单，无法创建工单。"}

        ticket_id = f"OTK-{uuid4().hex[:8].upper()}"
        connection.execute(
            """
            INSERT INTO olist_support_tickets(
                id, order_alias, category, summary, status, idempotency_key, created_at
            ) VALUES (?, ?, ?, ?, '待处理', ?, ?)
            """,
            (
                ticket_id,
                alias,
                category,
                summary,
                idempotency_key,
                datetime.now(UTC).isoformat(),
            ),
        )
        connection.commit()
    finally:
        connection.close()
    return {
        "ok": True,
        "ticket_id": ticket_id,
        "status": "待处理",
        "duplicate": False,
    }
