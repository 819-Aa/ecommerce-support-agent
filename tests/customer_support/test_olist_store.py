import sqlite3
from pathlib import Path

import pytest

import customer_support.olist_store as olist_store
from customer_support.olist_store import (
    create_olist_support_ticket,
    get_olist_order_status,
    is_olist_order_id,
    olist_refund_eligibility,
)
from customer_support.store import get_order_status


@pytest.fixture
def olist_db(tmp_path: Path) -> Path:
    path = tmp_path / "olist.db"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE olist_customers (
                customer_id TEXT PRIMARY KEY,
                demo_phone_last4 TEXT,
                customer_city TEXT,
                customer_state TEXT
            );
            CREATE TABLE olist_orders (
                order_alias TEXT PRIMARY KEY,
                customer_id TEXT,
                status_zh TEXT,
                order_purchase_timestamp TEXT,
                order_delivered_customer_date TEXT,
                order_estimated_delivery_date TEXT,
                days_since_delivery INTEGER,
                delivery_delay_days INTEGER,
                is_delivery_late INTEGER
            );
            CREATE TABLE olist_order_items (
                order_alias TEXT,
                product_id TEXT,
                price REAL,
                freight_value REAL
            );
            CREATE TABLE olist_products (
                product_id TEXT PRIMARY KEY,
                product_category_name TEXT,
                product_category_name_english TEXT
            );
            CREATE TABLE olist_order_payments (
                order_alias TEXT,
                payment_value REAL,
                payment_type TEXT
            );
            CREATE TABLE olist_order_reviews (
                order_alias TEXT,
                review_score INTEGER
            );
            CREATE TABLE olist_support_tickets (
                id TEXT PRIMARY KEY,
                order_alias TEXT,
                category TEXT,
                summary TEXT,
                status TEXT,
                idempotency_key TEXT UNIQUE,
                created_at TEXT
            );
            INSERT INTO olist_customers
                VALUES ('C-REAL', '0347', 'sao paulo', 'SP');
            INSERT INTO olist_orders VALUES (
                'OL000001', 'C-REAL', '已签收',
                '2018-10-10 10:00:00', '2018-10-17 10:00:00',
                '2018-10-20 00:00:00', 3, -3, 0
            );
            INSERT INTO olist_order_items
                VALUES ('OL000001', 'P1', 100.0, 12.5);
            INSERT INTO olist_products
                VALUES ('P1', 'informatica_acessorios', 'computers_accessories');
            INSERT INTO olist_order_payments
                VALUES ('OL000001', 112.5, 'credit_card');
            INSERT INTO olist_order_reviews VALUES ('OL000001', 5);
            """
        )
    return path


def test_olist_order_query_and_identity_check(olist_db: Path):
    result = get_olist_order_status("OL000001", "0347", olist_db)
    rejected = get_olist_order_status("OL000001", "0000", olist_db)
    missing = get_olist_order_status("OL999999", "0000", olist_db)

    assert result["status"] == "已签收"
    assert result["product_name"] == "computers accessories"
    assert result["payment_total"] == 112.5
    assert result["data_source"] == "Olist匿名公开电商数据"
    assert rejected["error_code"] == "ORDER_NOT_FOUND_OR_VERIFICATION_FAILED"
    assert missing == rejected


def test_missing_item_condition_requires_manual_refund_review(olist_db: Path):
    result = olist_refund_eligibility("OL000001", "0347", olist_db)

    assert result["eligible"] is None
    assert result["requires_manual_review"] is True
    assert "没有商品是否拆封字段" in result["reason"]


def test_olist_ticket_is_idempotent(olist_db: Path):
    first = create_olist_support_ticket(
        "OL000001", "退款审核", "缺少商品状态", "same-key", olist_db
    )
    second = create_olist_support_ticket(
        "OL000001", "退款审核", "缺少商品状态", "same-key", olist_db
    )

    assert first["ticket_id"] == second["ticket_id"]
    assert first["duplicate"] is False
    assert second["duplicate"] is True


def test_unified_store_dispatches_ol_alias(
    olist_db: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(olist_store, "DEFAULT_OLIST_DB_PATH", olist_db)

    result = get_order_status("OL000001", "0347")

    assert is_olist_order_id("OL000001")
    assert not is_olist_order_id("ORD1001")
    assert result["data_source"] == "Olist匿名公开电商数据"
