"""UTF-8 checks for the configured online tool-calling model inside Docker."""

from __future__ import annotations

import json
import sys
import urllib.request
from uuid import uuid4

ENDPOINT = "http://127.0.0.1:8080/customer-support/invoke"


def ask(message: str, scenario: str) -> str:
    payload = json.dumps(
        {
            "message": message,
            "thread_id": f"docker-{scenario}-{uuid4()}",
            "user_id": "docker-e2e-user",
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        ENDPOINT,
        data=payload,
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    with urllib.request.urlopen(request, timeout=300) as response:
        result = json.loads(response.read().decode("utf-8"))
    return result["content"]


def check(name: str, answer: str, expected_terms: tuple[str, ...]) -> bool:
    passed = all(term in answer for term in expected_terms)
    print(f"[{'通过' if passed else '失败'}] {name}")
    print(answer)
    print()
    return passed


def main() -> int:
    order_answer = ask(
        "查询订单 OL099422，手机号后四位 3623，并告诉我物流是否延迟",
        "order",
    )
    policy_answer = ask(
        "七天无理由退款需要满足什么条件？请标注政策来源",
        "policy",
    )
    results = [
        check("在线模型 → Function Calling → MySQL", order_answer, ("运输中", "延迟")),
        check(
            "在线模型 → 政策路由 → Chroma RAG",
            policy_answer,
            ("customer_service_policy.md", "退款"),
        ),
    ]
    passed = sum(results)
    print(f"在线模型容器端到端验收：{passed}/{len(results)} 项通过")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
