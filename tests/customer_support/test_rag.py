from __future__ import annotations

import hashlib
from pathlib import Path

from langchain_core.embeddings import Embeddings

from customer_support.policy import load_policy_sections
from customer_support.rag import PolicyKnowledgeBase, load_policy_chunks


class HashEmbeddings(Embeddings):
    """Small deterministic test double; real code uses BGE Chinese embeddings."""

    dimensions = 32

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for index in range(max(1, len(text) - 1)):
            token = text[index : index + 2]
            bucket = int(hashlib.sha1(token.encode()).hexdigest()[:8], 16)
            vector[bucket % self.dimensions] += 1.0
        return vector

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


def test_policy_markdown_is_parsed_and_chunked():
    sections = load_policy_sections()
    chunks = load_policy_chunks()

    assert [section.title for section in sections] == [
        "七天无理由退款",
        "特殊商品退换限制",
        "退款到账时效",
        "换货与缺件补发",
        "订单取消",
        "物流时效与轨迹",
        "物流异常",
        "收货地址修改",
        "商品保修",
        "维修申请与进度",
        "发票服务",
        "支付与重复扣款",
        "优惠券与促销",
        "账户与隐私",
        "客服升级与工单",
        "投诉与服务时效",
    ]
    assert len(chunks) >= len(sections)
    assert chunks[0].metadata["source"].endswith("customer_service_policy.md")


def test_hybrid_search_returns_cited_policy(tmp_path: Path):
    knowledge_base = PolicyKnowledgeBase(
        persist_directory=tmp_path / "chroma",
        embedding=HashEmbeddings(),
    )

    hits = knowledge_base.search("电子产品进水了还能保修吗", top_k=2)

    assert hits[0]["title"] == "商品保修"
    assert "进水" in hits[0]["content"]
    assert hits[0]["dense_rank"] is not None
    assert hits[0]["lexical_rank"] is not None


def test_index_is_reused_when_policy_does_not_change(tmp_path: Path):
    knowledge_base = PolicyKnowledgeBase(
        persist_directory=tmp_path / "chroma",
        embedding=HashEmbeddings(),
    )

    first_count = knowledge_base.ensure_index()
    manifest_before = knowledge_base.manifest_path.read_text(encoding="utf-8")
    second_count = knowledge_base.ensure_index()

    assert first_count == second_count == len(load_policy_chunks())
    assert knowledge_base.manifest_path.read_text(encoding="utf-8") == manifest_before


def test_dense_search_can_reject_unrelated_question(tmp_path: Path):
    knowledge_base = PolicyKnowledgeBase(
        persist_directory=tmp_path / "chroma",
        embedding=HashEmbeddings(),
        relevance_threshold=0.95,
    )

    hits = knowledge_base.search("请解释快速排序的时间复杂度", top_k=2, method="dense")

    assert hits == []
