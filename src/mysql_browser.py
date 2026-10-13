"""Read-only Streamlit browser backed by the FastAPI service."""

from __future__ import annotations

import math
import os
from typing import Any

import httpx
import pandas as pd
import streamlit as st

AGENT_URL = os.getenv("AGENT_URL", "http://127.0.0.1:8080")


@st.cache_data(ttl=10)
def api_get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    response = httpx.get(f"{AGENT_URL}{path}", params=params, timeout=10)
    response.raise_for_status()
    return response.json()


st.set_page_config(page_title="MySQL 数据浏览器", page_icon="🗄️", layout="wide")
st.title("MySQL 业务数据浏览器")
st.caption("只读页面：通过 FastAPI 查看数据，不能 UPDATE 或 DELETE。")

try:
    tables = api_get("/database/tables")["tables"]
except Exception as error:
    st.error(f"无法连接后端：{error}")
    st.stop()

table = st.selectbox("选择数据表", tables, index=tables.index("olist_orders"))
order_alias = ""
if table == "olist_orders":
    order_alias = st.text_input(
        "按演示订单号查询（可选）",
        placeholder="例如 OL099422",
    )

page_size = st.selectbox("每页行数", [20, 50, 100], index=0)
initial = api_get(
    f"/database/tables/{table}",
    {"limit": page_size, "offset": 0, "order_alias": order_alias},
)
total = int(initial["total"])
st.write(f"表 `{table}` 共 **{total:,}** 行")
if table in {"support_tickets", "olist_support_tickets"}:
    st.caption("`created_at` 已从数据库UTC时间转换为北京时间（Asia/Shanghai）。")

page_count = max(1, math.ceil(total / page_size))
page = int(st.number_input("页码", min_value=1, max_value=page_count, value=1))
result = (
    initial
    if page == 1
    else api_get(
        f"/database/tables/{table}",
        {
            "limit": page_size,
            "offset": (page - 1) * page_size,
            "order_alias": order_alias,
        },
    )
)

if result["rows"]:
    st.dataframe(
        pd.DataFrame(result["rows"]),
        use_container_width=True,
        hide_index=True,
    )
else:
    st.info("没有找到符合条件的数据。")

st.divider()
st.markdown(
    """
**数据说明**

- `olist_*`：Olist 匿名真实电商数据及关联工单。
- `orders/customers`：用于稳定演示的 3 笔模拟订单。
- `migration_history`：记录 SQLite → MySQL 的迁移摘要。
"""
)
