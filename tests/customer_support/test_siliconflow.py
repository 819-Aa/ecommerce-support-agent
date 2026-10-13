"""Contracts for remote embedding, reranking and the configured chat agent."""

import json
from pathlib import Path

import httpx
import pytest
from langchain_core.embeddings import DeterministicFakeEmbedding
from pydantic import SecretStr

from customer_support import rag


def test_embeddings_keep_input_order_when_api_returns_unsorted_indices():
    def respond(request):
        assert request.url.path == "/v1/embeddings"
        assert json.loads(request.content)["input"] == ["退款", "发票"]
        return httpx.Response(
            200,
            json={
                "object": "list",
                "model": "BAAI/bge-m3",
                "data": [
                    {"object": "embedding", "index": 1, "embedding": [0.0, 1.0]},
                    {"object": "embedding", "index": 0, "embedding": [1.0, 0.0]},
                ],
                "usage": {"prompt_tokens": 4, "total_tokens": 4},
            },
        )

    embedding = rag.SiliconFlowEmbeddings(
        api_key="test-secret",
        client=httpx.Client(transport=httpx.MockTransport(respond)),
    )
    assert embedding.embed_documents(["退款", "发票"]) == [[1.0, 0.0], [0.0, 1.0]]


def test_query_embedding_uses_same_model_and_vector_format_as_documents():
    def respond(request):
        payload = json.loads(request.content)
        assert payload["model"] == "BAAI/bge-m3"
        assert payload["encoding_format"] == "float"
        assert payload["input"] == ["能退款吗"]
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 0, "embedding": [0.25, 0.75]},
                ]
            },
        )

    embedding = rag.SiliconFlowEmbeddings(
        api_key="test-secret",
        client=httpx.Client(transport=httpx.MockTransport(respond)),
    )
    assert embedding.embed_query("能退款吗") == [0.25, 0.75]


def test_embedding_api_error_does_not_expose_key_or_response_body():
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(401, text="test-secret: invalid token"),
        )
    )
    embedding = rag.SiliconFlowEmbeddings(api_key="test-secret", client=client)
    with pytest.raises(RuntimeError, match="401") as error:
        embedding.embed_query("退款")
    assert "test-secret" not in str(error.value)


def test_embedding_rejects_missing_vector_instead_of_corrupting_index():
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"data": []}),
        )
    )
    embedding = rag.SiliconFlowEmbeddings(api_key="test-secret", client=client)
    with pytest.raises(ValueError, match="embedding"):
        embedding.embed_documents(["退款"])


def test_reranker_preserves_document_indices():
    def respond(request):
        assert request.url.path == "/v1/rerank"
        payload = json.loads(request.content)
        assert payload["documents"] == ["退款", "发票", "物流"]
        assert payload["top_n"] == 2
        return httpx.Response(
            200,
            json={
                "results": [
                    {"index": 2, "relevance_score": 0.9},
                    {"index": 0, "relevance_score": 0.8},
                ]
            },
        )

    reranker = rag.SiliconFlowReranker(
        api_key="test-secret",
        client=httpx.Client(transport=httpx.MockTransport(respond)),
    )
    assert reranker.rerank("快递", ["退款", "发票", "物流"], top_n=2) == [(2, 0.9), (0, 0.8)]


def test_reranker_rejects_indices_outside_candidate_list():
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "results": [
                        {"index": 99, "relevance_score": 0.9},
                    ]
                },
            ),
        )
    )
    reranker = rag.SiliconFlowReranker(api_key="test-secret", client=client)
    with pytest.raises(ValueError, match="rerank"):
        reranker.rerank("退款", ["退款"], top_n=1)


def test_hybrid_rerank_applies_remote_order_before_top_k(tmp_path: Path):
    policy = tmp_path / "policy.md"
    policy.write_text("## 退款\n退款需要满足条件。\n## 发票\n发票可以申请补开。", encoding="utf-8")

    def respond(request):
        documents = json.loads(request.content)["documents"]
        invoice_index = next(i for i, text in enumerate(documents) if "发票" in text)
        return httpx.Response(
            200,
            json={
                "results": [
                    {"index": invoice_index, "relevance_score": 0.95},
                ]
            },
        )

    kb = rag.PolicyKnowledgeBase(
        policy_path=policy,
        persist_directory=tmp_path / "chroma",
        embedding=DeterministicFakeEmbedding(size=8),
        relevance_threshold=-10,
        reranker=rag.SiliconFlowReranker(
            api_key="test-secret",
            client=httpx.Client(transport=httpx.MockTransport(respond)),
        ),
    )
    assert kb.search("退款", top_k=1, method="hybrid")[0]["title"] == "退款"
    hits = kb.search("退款", top_k=1, method="hybrid_rerank")
    assert hits[0]["title"] == "发票"
    assert hits[0]["rerank_score"] == 0.95
    assert hits[0]["source"] == policy.as_posix()


def test_remote_rag_configuration_requires_key_without_local_fallback(monkeypatch):
    monkeypatch.setenv("RAG_EMBEDDING_PROVIDER", "siliconflow")
    monkeypatch.setenv("SILICONFLOW_API_KEY", "")
    rag.get_policy_knowledge_base.cache_clear()
    try:
        with pytest.raises(ValueError, match="SILICONFLOW_API_KEY"):
            rag.get_policy_knowledge_base()
    finally:
        rag.get_policy_knowledge_base.cache_clear()


@pytest.mark.asyncio
async def test_compatible_mode_builds_deepseek_tool_graph(monkeypatch):
    import agents.customer_support_agent as agent_module

    monkeypatch.setattr(agent_module.settings, "CUSTOMER_SUPPORT_MODE", "compatible")
    monkeypatch.setattr(agent_module.settings, "COMPATIBLE_API_KEY", SecretStr("test-secret"))
    monkeypatch.setattr(
        agent_module.settings, "COMPATIBLE_BASE_URL", "https://api.siliconflow.cn/v1"
    )
    monkeypatch.setattr(agent_module.settings, "COMPATIBLE_MODEL", "deepseek-ai/DeepSeek-V4-Flash")
    captured = []
    build = agent_module.build_customer_support_graph

    def capture_model(model):
        captured.append(model)
        return build(model)

    monkeypatch.setattr(agent_module, "build_customer_support_graph", capture_model)
    agent = agent_module.CustomerSupportAgent()
    await agent.load()
    assert agent.get_graph() is not None
    assert captured[0].model_name == "deepseek-ai/DeepSeek-V4-Flash"
    assert captured[0].openai_api_base == "https://api.siliconflow.cn/v1"
    assert captured[0].streaming is True


@pytest.mark.asyncio
async def test_compatible_mode_missing_key_fails_instead_of_using_mock(monkeypatch):
    import agents.customer_support_agent as agent_module

    monkeypatch.setattr(agent_module.settings, "CUSTOMER_SUPPORT_MODE", "compatible")
    monkeypatch.setattr(agent_module.settings, "COMPATIBLE_API_KEY", None)
    agent = agent_module.CustomerSupportAgent()
    with pytest.raises(ValueError, match="COMPATIBLE_API_KEY"):
        await agent.load()
