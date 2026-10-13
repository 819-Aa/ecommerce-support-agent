import sqlite3
from pathlib import Path

import pytest
from langchain.agents.middleware import ModelRequest, ModelResponse
from langchain_core.language_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolCall, ToolMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

import customer_support.store as store
from agents.customer_support_agent import (
    _forced_tool_for_message,
    build_customer_support_graph,
    deterministic_tool_routing,
)
from customer_support.tools import CUSTOMER_SUPPORT_TOOLS
from service.service import _format_interrupt, _hitl_resume_value


class FakeToolModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


@pytest.fixture
def isolated_business_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(store, "DEFAULT_DB_PATH", tmp_path / "support.db")


@pytest.mark.asyncio
async def test_qwen_graph_executes_read_only_order_tool(isolated_business_db):
    model = FakeToolModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    ToolCall(
                        name="get_order_status",
                        args={"order_id": "ORD1001", "phone_last4": "8821"},
                        id="call-order",
                    )
                ],
            ),
            AIMessage(content="订单 ORD1001 当前正在运输中。"),
        ]
    )
    graph = build_customer_support_graph(model)

    result = await graph.ainvoke(
        {"messages": [HumanMessage(content="查询订单 ORD1001，手机号后四位 8821")]}
    )

    tool_messages = [message for message in result["messages"] if isinstance(message, ToolMessage)]
    assert '"status": "运输中"' in tool_messages[0].content
    assert result["messages"][-1].content == "订单 ORD1001 当前正在运输中。"


@pytest.mark.asyncio
async def test_ticket_tool_is_interrupted_until_approved(isolated_business_db):
    model = FakeToolModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    ToolCall(
                        name="create_support_ticket",
                        args={
                            "order_id": "ORD1001",
                            "phone_last4": "8821",
                            "category": "物流异常",
                            "summary": "订单物流长时间未更新",
                        },
                        id="call-ticket",
                    )
                ],
            ),
            AIMessage(content="客服工单已经创建。"),
        ]
    )
    graph = build_customer_support_graph(model)
    graph.checkpointer = MemorySaver()
    config = {"configurable": {"thread_id": "ticket-thread"}}

    interrupted = await graph.ainvoke(
        {"messages": [HumanMessage(content="帮我创建物流工单")]},
        config=config,
    )
    interrupt_value = interrupted["__interrupt__"][0].value

    assert "create_support_ticket" in _format_interrupt(interrupt_value)
    assert _hitl_resume_value("确认", interrupt_value) == {"decisions": [{"type": "approve"}]}

    completed = await graph.ainvoke(
        Command(resume=_hitl_resume_value("确认", interrupt_value)),
        config=config,
    )

    tool_messages = [
        message for message in completed["messages"] if isinstance(message, ToolMessage)
    ]
    assert '"ticket_id":' in tool_messages[-1].content
    assert completed["messages"][-1].content == "客服工单已经创建。"


def test_non_confirmation_rejects_write_action():
    interrupt_value = {
        "action_requests": [{"name": "create_support_ticket", "args": {"order_id": "ORD1001"}}]
    }

    result = _hitl_resume_value("我再想想", interrupt_value)

    assert result["decisions"][0]["type"] == "reject"


@pytest.mark.asyncio
@pytest.mark.parametrize("with_read_tool", [False, True])
async def test_rejected_ticket_finishes_without_model_requesting_confirmation_again(
    isolated_business_db,
    with_read_tool,
):
    tool_calls = [
        ToolCall(
            name="create_support_ticket",
            args={
                "order_id": "ORD1001",
                "phone_last4": "8821",
                "category": "人工处理",
                "summary": "取消场景验收",
            },
            id="cancel-ticket",
        ),
    ]
    if with_read_tool:
        tool_calls.append(
            ToolCall(
                name="get_order_status",
                args={"order_id": "ORD1001", "phone_last4": "8821"},
                id="read-order",
            )
        )
    model = FakeToolModel(
        responses=[
            AIMessage(content="", tool_calls=tool_calls),
            AIMessage(content="请确认后我将为您提交。"),
        ]
    )
    graph = build_customer_support_graph(model)
    graph.checkpointer = MemorySaver()
    config = {"configurable": {"thread_id": "cancel-thread"}}
    pending = await graph.ainvoke(
        {"messages": [HumanMessage(content="帮我创建人工工单")]},
        config=config,
    )
    result = await graph.ainvoke(
        Command(resume=_hitl_resume_value("取消", pending["__interrupt__"][0].value)),
        config=config,
    )
    assert "取消" in result["messages"][-1].content
    assert not result["messages"][-1].tool_calls
    assert not (await graph.aget_state(config)).next
    path = store.initialize_database()
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM support_tickets").fetchone()[0] == 0


def test_clear_business_intents_get_deterministic_tool_routing():
    assert _forced_tool_for_message("七天无理由退款需要满足什么条件？") == "search_policy"
    assert (
        _forced_tool_for_message("查询订单 OL099422，手机号后四位 3623，并告诉我物流是否延迟")
        == "get_order_status"
    )
    assert (
        _forced_tool_for_message("订单 ORD1002 能退款吗？手机号后四位 8821")
        == "check_refund_eligibility"
    )
    assert _forced_tool_for_message("你好") is None


def test_deterministic_router_covers_extended_policy_intents():
    assert _forced_tool_for_message("优惠券取消订单后会退回吗？") == "search_policy"
    assert _forced_tool_for_message("支付失败但是银行卡扣款了怎么办？") == "search_policy"
    assert _forced_tool_for_message("订单出库后还能修改收货地址吗？") == "search_policy"
    assert _forced_tool_for_message("客服会不会向我要短信验证码？") == "search_policy"


@pytest.mark.asyncio
async def test_middleware_reads_latest_message_from_agent_state():
    model = FakeToolModel(responses=[AIMessage(content="unused")])
    request = ModelRequest(
        model=model,
        messages=[],
        state={"messages": [HumanMessage(content="七天无理由退款需要满足什么条件？")]},
        tools=CUSTOMER_SUPPORT_TOOLS,
    )
    captured = {}

    async def handler(updated_request):
        captured["tool_choice"] = updated_request.tool_choice
        captured["tools"] = [tool.name for tool in updated_request.tools]
        return ModelResponse(result=[AIMessage(content="ok")])

    await deterministic_tool_routing.awrap_model_call(request, handler)

    assert captured == {
        "tool_choice": "search_policy",
        "tools": ["search_policy"],
    }
