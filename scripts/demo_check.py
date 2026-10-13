"""Beginner-friendly end-to-end checks against the running FastAPI service."""

from __future__ import annotations

import sys
from uuid import uuid4

import httpx

BASE_URL = "http://127.0.0.1:8080"


def ask(message: str, thread_id: str) -> str:
    response = httpx.post(
        f"{BASE_URL}/customer-support/invoke",
        json={"message": message, "thread_id": thread_id, "user_id": "demo-user"},
        timeout=20,
    )
    response.raise_for_status()
    return response.json()["content"]


def check(name: str, actual: str, expected: str) -> bool:
    passed = expected in actual
    symbol = "通过" if passed else "失败"
    print(f"[{symbol}] {name}")
    if not passed:
        print(f"  期望包含：{expected}")
        print(f"  实际结果：{actual}")
    return passed


def check_any(name: str, actual: str, expected_options: tuple[str, ...]) -> bool:
    """Accept equivalent natural-language answers while still checking business facts."""
    passed = any(expected in actual for expected in expected_options)
    symbol = "通过" if passed else "失败"
    print(f"[{symbol}] {name}")
    if not passed:
        print(f"  期望至少包含一项：{expected_options}")
        print(f"  实际结果：{actual}")
    return passed


def main() -> int:
    try:
        health = httpx.get(f"{BASE_URL}/health", timeout=5)
        health.raise_for_status()
    except Exception:
        print("FastAPI 尚未启动。请先运行 .\\scripts\\start_demo.cmd")
        return 1

    results = [
        check(
            "政策问答带来源",
            ask("七天无理由退款有什么要求？", f"policy-{uuid4()}"),
            "customer_service_policy.md",
        ),
        check(
            "同义表达进入语义检索",
            ask(
                "商城对快递长时间不更新有什么处理规定？请标注来源。",
                f"semantic-{uuid4()}",
            ),
            "物流时效与轨迹",
        ),
        check(
            "订单字样不会抢走发票政策问题",
            ask("订单完成40天后还能申请电子发票吗？", f"invoice-{uuid4()}"),
            "45 天",
        ),
        check(
            "正确身份可以查询订单",
            ask("查询订单 ORD1001，手机号后四位 8821", f"order-{uuid4()}"),
            "运输中",
        ),
        check_any(
            "错误身份禁止泄露订单",
            ask("查询订单 ORD1001，手机号后四位 0000", f"privacy-{uuid4()}"),
            ("验证失败", "验证信息不匹配"),
        ),
        check_any(
            "符合七天退款规则",
            ask("订单 ORD1002 能退款吗？手机号后四位 8821", f"refund-{uuid4()}"),
            ("可以申请", "符合退款资格"),
        ),
        check_any(
            "超期订单被拒绝",
            ask("订单 ORD1003 能退款吗？手机号后四位 8821", f"expired-{uuid4()}"),
            ("暂不符合", "不符合退款资格"),
        ),
    ]

    ticket_thread = f"ticket-{uuid4()}"
    results.append(
        check(
            "写操作先请求确认",
            ask(
                "为 ORD1001 创建物流异常工单，手机号后四位 8821，摘要为订单物流长期未更新",
                ticket_thread,
            ),
            "请回复“确认”",
        )
    )
    results.append(
        check_any(
            "确认后创建工单",
            ask("确认", ticket_thread),
            ("工单已创建", "工单创建成功", "工单已存在", "无需重复创建"),
        )
    )

    passed = sum(results)
    print(f"\n验收结果：{passed}/{len(results)} 项通过")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
