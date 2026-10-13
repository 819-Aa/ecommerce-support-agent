"""Small deterministic acceptance check for the Docker deployment."""

from __future__ import annotations

import json
import subprocess
import sys
import urllib.request


def http_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def mysql_scalar(sql: str) -> str:
    command = [
        "docker",
        "compose",
        "exec",
        "-T",
        "mysql",
        "sh",
        "-c",
        ('mysql -N -B -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE" -e "$1"'),
        "verify-docker",
        sql,
    ]
    result = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip()


def check(name: str, condition: bool, detail: str) -> bool:
    print(f"[{'通过' if condition else '失败'}] {name}: {detail}")
    return condition


def main() -> int:
    results: list[bool] = []
    try:
        readiness = http_json("http://127.0.0.1:8080/ready")
        results.append(
            check(
                "FastAPI + MySQL 就绪检查",
                readiness.get("backend") == "mysql" and readiness.get("order_count") == 99441,
                f"后端={readiness.get('backend')}，订单={readiness.get('order_count')}",
            )
        )
    except Exception as error:
        results.append(check("FastAPI 健康检查", False, str(error)))

    try:
        with urllib.request.urlopen("http://127.0.0.1:8501/_stcore/health", timeout=10) as response:
            body = response.read().decode("utf-8")
        results.append(check("Streamlit 健康检查", body == "ok", body))
    except Exception as error:
        results.append(check("Streamlit 健康检查", False, str(error)))

    try:
        with urllib.request.urlopen("http://127.0.0.1:8081/_stcore/health", timeout=10) as response:
            body = response.read().decode("utf-8")
        results.append(check("只读 MySQL 浏览器", body == "ok", body))
    except Exception as error:
        results.append(check("只读 MySQL 浏览器", False, str(error)))

    try:
        order_count = int(mysql_scalar("SELECT COUNT(*) FROM olist_orders;"))
        item_count = int(mysql_scalar("SELECT COUNT(*) FROM olist_order_items;"))
        results.append(check("MySQL 真实订单", order_count == 99441, f"{order_count:,} 条"))
        results.append(check("MySQL 订单明细", item_count == 112650, f"{item_count:,} 条"))
    except Exception as error:
        results.append(check("MySQL 数据检查", False, str(error)))

    passed = sum(results)
    print(f"\nDocker 验收结果：{passed}/{len(results)} 项通过")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
