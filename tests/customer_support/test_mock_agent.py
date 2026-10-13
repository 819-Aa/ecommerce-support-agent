from pathlib import Path

import pytest
from langchain_core.messages import HumanMessage

import agents.customer_support_mock as customer_support_agent
import customer_support.store as store
from agents.customer_support_mock import customer_support_node


@pytest.fixture
def isolated_business_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(store, "DEFAULT_DB_PATH", tmp_path / "support.db")

    def fake_policy_search(query: str):
        if "真人" in query:
            title = "客服升级与工单"
            content = "知识库无法回答时可以转人工处理。"
        elif "发票" in query:
            title = "发票服务"
            content = "订单完成后 45 天内可以申请电子发票。"
        else:
            title = "七天无理由退款"
            content = "商品保持未拆封且不影响二次销售时可以申请。"
        return {
            "title": title,
            "content": content,
            "source": "data/policies/customer_service_policy.md",
            "score": 0.18,
        }

    monkeypatch.setattr(
        customer_support_agent,
        "search_policy",
        fake_policy_search,
    )


@pytest.mark.asyncio
async def test_policy_question_returns_source(isolated_business_db):
    result = await customer_support_node(
        {"messages": [HumanMessage(content="七天无理由退款有什么要求？")]}
    )

    answer = result["messages"][-1].content
    assert "未拆封" in answer
    assert "customer_service_policy.md" in answer


@pytest.mark.asyncio
async def test_policy_synonym_is_routed_to_rag(isolated_business_db):
    result = await customer_support_node(
        {"messages": [HumanMessage(content="机器人答不上来，我想找真人处理。")]}
    )

    answer = result["messages"][-1].content
    assert "客服升级与工单" in answer
    assert "转人工" in answer


@pytest.mark.asyncio
async def test_policy_question_with_order_word_is_not_misrouted(isolated_business_db):
    result = await customer_support_node(
        {"messages": [HumanMessage(content="订单完成40天后还能申请电子发票吗？")]}
    )

    answer = result["messages"][-1].content
    assert "发票服务" in answer
    assert "45 天" in answer
    assert "请提供订单号" not in answer


@pytest.mark.asyncio
async def test_order_lookup_requires_identity_verification(isolated_business_db):
    missing_phone = await customer_support_node(
        {"messages": [HumanMessage(content="查询订单 ORD1001")]}
    )
    wrong_phone = await customer_support_node(
        {"messages": [HumanMessage(content="查询订单 ORD1001，手机号后四位 0000")]}
    )

    assert "手机号后四位" in missing_phone["messages"][-1].content
    assert "验证信息不匹配" in wrong_phone["messages"][-1].content


@pytest.mark.asyncio
async def test_ticket_requires_confirmation(isolated_business_db):
    first = await customer_support_node(
        {"messages": [HumanMessage(content="为 ORD1001 创建人工客服工单，手机号后四位 8821")]}
    )

    assert "请回复“确认”" in first["messages"][-1].content
    assert first["pending_ticket"]["order_id"] == "ORD1001"

    confirmed = await customer_support_node(
        {
            "messages": [HumanMessage(content="确认")],
            "pending_ticket": first["pending_ticket"],
        }
    )

    assert "工单已创建" in confirmed["messages"][-1].content
    assert confirmed["pending_ticket"] is None
