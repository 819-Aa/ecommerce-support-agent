"""Deterministic offline customer-support agent for the first milestone."""

from __future__ import annotations

import re
from typing import Any

from langchain_core.messages import AIMessage
from langgraph.graph import END, MessagesState, StateGraph

from customer_support.policy import search_policy
from customer_support.store import (
    create_support_ticket,
    get_order_status,
    initialize_database,
    refund_eligibility,
)


class CustomerSupportState(MessagesState, total=False):
    pending_ticket: dict[str, str] | None


def _message_text(message: Any) -> str:
    content = message.content
    return content if isinstance(content, str) else str(content)


def _order_id(text: str) -> str | None:
    match = re.search(r"\bORD\d{4}\b", text.upper())
    return match.group(0) if match else None


def _phone_last4(text: str, order_id: str | None) -> str | None:
    explicit = re.search(r"(?:后四位|尾号|手机号)[：:\s]*(\d{4})", text)
    if explicit:
        return explicit.group(1)
    candidates = re.findall(r"(?<![A-Za-z])\b\d{4}\b", text)
    order_suffix = order_id[-4:] if order_id else None
    return next((candidate for candidate in candidates if candidate != order_suffix), None)


def _ai(content: str) -> AIMessage:
    return AIMessage(content=content)


async def customer_support_node(state: CustomerSupportState) -> CustomerSupportState:
    """Route a small set of testable customer-support intents without an API."""
    initialize_database()
    text = _message_text(state["messages"][-1]).strip()
    pending = state.get("pending_ticket")

    if pending:
        if any(word in text for word in ("取消", "不要", "否")):
            return {
                "messages": [_ai("已取消，本次不会创建客服工单。")],
                "pending_ticket": None,
            }
        if any(word in text for word in ("确认", "同意", "好的", "是")):
            result = create_support_ticket(
                order_id=pending["order_id"],
                category=pending["category"],
                summary=pending["summary"],
                idempotency_key=pending["idempotency_key"],
            )
            return {
                "messages": [
                    _ai(
                        f"工单已创建：{result['ticket_id']}，状态为{result['status']}。"
                        "客服人员会继续处理。"
                    )
                ],
                "pending_ticket": None,
            }
        return {
            "messages": [_ai("请回复“确认”创建工单，或回复“取消”。")],
            "pending_ticket": pending,
        }

    order_id = _order_id(text)
    phone_last4 = _phone_last4(text, order_id)

    if "工单" in text or "人工客服" in text:
        if not order_id:
            return {"messages": [_ai("请提供订单号，例如 ORD1001。")]}
        if not phone_last4:
            return {"messages": [_ai("为保护隐私，请提供下单手机号后四位。")]}
        order = get_order_status(order_id, phone_last4)
        if not order["ok"]:
            return {"messages": [_ai(order["error"])]}
        pending_ticket = {
            "order_id": order_id,
            "category": "售后咨询",
            "summary": f"用户为订单 {order_id} 申请人工客服处理。",
            "idempotency_key": f"{order_id}-after-sales",
        }
        return {
            "messages": [
                _ai(f"即将为订单 {order_id} 创建售后工单。这是写入操作，请回复“确认”或“取消”。")
            ],
            "pending_ticket": pending_ticket,
        }

    order_intent_words = ("查询订单", "查订单", "订单状态", "退款资格", "能退款")
    if order_id or any(word in text for word in order_intent_words):
        if not order_id:
            return {"messages": [_ai("请提供订单号，例如 ORD1002。")]}
        if not phone_last4:
            return {"messages": [_ai("为保护隐私，请提供下单手机号后四位。")]}
        if any(word in text for word in ("退款", "退货")):
            result = refund_eligibility(order_id, phone_last4)
            if not result["ok"]:
                return {"messages": [_ai(result["error"])]}
            conclusion = "可以申请" if result["eligible"] else "暂不符合"
            return {
                "messages": [
                    _ai(
                        f"订单 {order_id} 的退款判断：{conclusion}。\n\n"
                        f"原因：{result['reason']}\n\n"
                        "政策来源：`data/policies/customer_service_policy.md`"
                    )
                ]
            }
        result = get_order_status(order_id, phone_last4)
        if not result["ok"]:
            return {"messages": [_ai(result["error"])]}
        return {
            "messages": [
                _ai(f"订单 {order_id}：{result['product_name']}，当前状态为“{result['status']}”。")
            ]
        }

    if any(
        word in text
        for word in (
            "退款",
            "退货",
            "退掉",
            "七天",
            "物流",
            "快递",
            "包裹",
            "运输",
            "保修",
            "维修",
            "售后",
            "进水",
            "发票",
            "开票",
            "补票",
            "报销",
            "配送",
            "机器人",
            "真人",
            "人工审核",
        )
    ):
        policy = search_policy(text)
        reference = f"{policy['source']} > {policy['title']}"
        return {
            "messages": [
                _ai(
                    f"### {policy['title']}\n\n{policy['content']}\n\n"
                    f"来源：`{reference}`\n\n"
                    f"检索分数：`{policy['score']:.4f}`"
                )
            ]
        }

    return {
        "messages": [
            _ai(
                "你好，我可以帮助你：\n"
                "- 查询退款、物流、保修和发票政策；\n"
                "- 查询订单状态；\n"
                "- 判断退款资格；\n"
                "- 确认后创建客服工单。\n\n"
                "测试示例：`查询订单 ORD1001，手机号后四位 8821`"
            )
        ]
    }


builder = StateGraph(CustomerSupportState)
builder.add_node("customer_support", customer_support_node)
builder.set_entry_point("customer_support")
builder.add_edge("customer_support", END)
customer_support_mock = builder.compile()
customer_support_mock.name = "CustomerSupportMock"
