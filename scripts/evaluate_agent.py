"""Deterministically evaluate routing, business rules, security, and idempotency."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from agents.customer_support_agent import _forced_tool_for_message  # noqa: E402
from customer_support.store import (  # noqa: E402
    create_support_ticket,
    get_order_status,
    initialize_database,
    refund_eligibility,
)

DEFAULT_CASES = Path("data/evaluation/agent_routing_cases.json")
DEFAULT_REPORT = Path("data/evaluation/agent_report.json")


def _check(name: str, condition: bool, actual: Any, expected: Any) -> dict[str, Any]:
    return {
        "name": name,
        "passed": bool(condition),
        "actual": actual,
        "expected": expected,
    }


def evaluate_routing(cases: list[dict[str, Any]]) -> dict[str, Any]:
    checks = []
    for case in cases:
        actual = _forced_tool_for_message(case["message"])
        checks.append(
            _check(case["message"], actual == case["expected_tool"], actual, case["expected_tool"])
        )
    passed = sum(check["passed"] for check in checks)
    return {
        "case_count": len(checks),
        "passed": passed,
        "accuracy": round(passed / len(checks), 4),
        "errors": [check for check in checks if not check["passed"]],
    }


def evaluate_business_rules(db_path: Path) -> dict[str, Any]:
    order = get_order_status("ORD1001", "8821", db_path)
    approved = refund_eligibility("ORD1002", "8821", db_path)
    expired = refund_eligibility("ORD1003", "8821", db_path)
    in_transit = refund_eligibility("ORD1001", "8821", db_path)
    checks = [
        _check("订单查询", order.get("status") == "运输中", order.get("status"), "运输中"),
        _check("退款通过", approved.get("eligible") is True, approved.get("eligible"), True),
        _check("超期拒绝", expired.get("eligible") is False, expired.get("eligible"), False),
        _check(
            "未签收拒绝", in_transit.get("eligible") is False, in_transit.get("eligible"), False
        ),
    ]
    return _summarize_checks(checks)


def evaluate_security(db_path: Path) -> dict[str, Any]:
    wrong_phone = get_order_status("ORD1001", "0000", db_path)
    missing_order = get_order_status("ORD9999", "0000", db_path)
    checks = [
        _check("错误手机号不泄露订单", wrong_phone.get("ok") is False, wrong_phone, {"ok": False}),
        _check(
            "不存在订单不泄露信息", missing_order.get("ok") is False, missing_order, {"ok": False}
        ),
        _check(
            "认证失败响应统一",
            wrong_phone == missing_order,
            wrong_phone,
            missing_order,
        ),
    ]
    return _summarize_checks(checks)


def evaluate_idempotency(db_path: Path) -> dict[str, Any]:
    kwargs = {
        "order_id": "ORD1001",
        "category": "物流异常",
        "summary": "验收用重复工单",
        "idempotency_key": "agent-evaluation-fixed-key",
        "db_path": db_path,
    }
    first = create_support_ticket(**kwargs)
    second = create_support_ticket(**kwargs)
    checks = [
        _check("首次创建", first.get("duplicate") is False, first, {"duplicate": False}),
        _check("重复请求复用工单", second.get("duplicate") is True, second, {"duplicate": True}),
        _check(
            "工单编号一致",
            first.get("ticket_id") == second.get("ticket_id"),
            second.get("ticket_id"),
            first.get("ticket_id"),
        ),
    ]
    return _summarize_checks(checks)


def _summarize_checks(checks: list[dict[str, Any]]) -> dict[str, Any]:
    passed = sum(check["passed"] for check in checks)
    return {
        "case_count": len(checks),
        "passed": passed,
        "accuracy": round(passed / len(checks), 4),
        "errors": [check for check in checks if not check["passed"]],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()

    routing_cases = json.loads(args.cases.read_text(encoding="utf-8"))
    with TemporaryDirectory(prefix="customer-support-eval-") as directory:
        db_path = Path(directory) / "support.db"
        initialize_database(db_path)
        sections = {
            "routing": evaluate_routing(routing_cases),
            "business_rules": evaluate_business_rules(db_path),
            "security": evaluate_security(db_path),
            "idempotency": evaluate_idempotency(db_path),
        }

    case_count = sum(section["case_count"] for section in sections.values())
    passed = sum(section["passed"] for section in sections.values())
    report = {
        "case_count": case_count,
        "passed": passed,
        "pass_rate": round(passed / case_count, 4),
        "sections": sections,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    for name, section in sections.items():
        print(
            f"{name:>16}: {section['passed']}/{section['case_count']} ({section['accuracy']:.0%})"
        )
    print(f"Agent业务验收：{passed}/{case_count} ({report['pass_rate']:.0%})")
    print(f"详细报告：{args.report}")
    return 0 if passed == case_count else 1


if __name__ == "__main__":
    raise SystemExit(main())
