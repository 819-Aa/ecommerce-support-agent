from pathlib import Path

import pytest

from customer_support.store import (
    create_support_ticket,
    get_order_status,
    initialize_database,
    refund_eligibility,
)


def test_mysql_backend_dispatch(monkeypatch: pytest.MonkeyPatch):
    import customer_support.mysql_store as mysql_store

    monkeypatch.setenv("BUSINESS_DATABASE_TYPE", "mysql")
    monkeypatch.setattr(
        mysql_store,
        "get_order_status",
        lambda order_id, phone_last4: {
            "ok": True,
            "order_id": order_id,
            "phone_last4": phone_last4,
            "backend": "mysql",
        },
    )

    result = get_order_status("ORD1001", "8821")

    assert result["backend"] == "mysql"


def test_seed_orders_and_identity_check(tmp_path: Path):
    db_path = tmp_path / "support.db"
    initialize_database(db_path)

    valid = get_order_status("ORD1001", "8821", db_path)
    invalid = get_order_status("ORD1001", "0000", db_path)
    missing = get_order_status("ORD9999", "0000", db_path)

    assert valid["ok"] is True
    assert valid["status"] == "运输中"
    assert invalid == {
        "ok": False,
        "error": "未找到订单或验证信息不匹配。",
        "error_code": "ORDER_NOT_FOUND_OR_VERIFICATION_FAILED",
    }
    assert missing == invalid


def test_refund_policy_has_positive_and_negative_cases(tmp_path: Path):
    db_path = tmp_path / "support.db"

    eligible = refund_eligibility("ORD1002", "8821", db_path)
    expired = refund_eligibility("ORD1003", "8821", db_path)
    in_transit = refund_eligibility("ORD1001", "8821", db_path)

    assert eligible["eligible"] is True
    assert expired["eligible"] is False
    assert "超过" in expired["reason"]
    assert in_transit["eligible"] is False
    assert "尚未签收" in in_transit["reason"]


def test_ticket_creation_is_idempotent(tmp_path: Path):
    db_path = tmp_path / "support.db"
    kwargs = {
        "order_id": "ORD1001",
        "category": "物流异常",
        "summary": "物流五天没有更新。",
        "idempotency_key": "demo-key",
        "db_path": db_path,
    }

    first = create_support_ticket(**kwargs)
    second = create_support_ticket(**kwargs)

    assert first["ok"] is True
    assert first["duplicate"] is False
    assert second["duplicate"] is True
    assert second["ticket_id"] == first["ticket_id"]
