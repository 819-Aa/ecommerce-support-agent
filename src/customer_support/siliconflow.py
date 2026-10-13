"""SiliconFlow text embeddings and reranking with validated responses."""

from __future__ import annotations

import math
from typing import Any

import httpx
from langchain_core.embeddings import Embeddings


class _SiliconFlowAPI:
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.siliconflow.cn/v1",
        client: httpx.Client | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("SILICONFLOW_API_KEY is required")
        self._api_key = api_key
        self.base_url = base_url.rstrip("/")
        self._client = client or httpx.Client(timeout=60)

    def _post(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = self._client.post(
                f"{self.base_url}/{endpoint}",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=payload,
            )
        except httpx.HTTPError:
            raise RuntimeError(f"SiliconFlow {endpoint} connection failed") from None
        if response.is_error:
            # Do not expose response bodies, request headers or upstream exceptions.
            raise RuntimeError(f"SiliconFlow {endpoint} HTTP {response.status_code}")
        try:
            result = response.json()
        except ValueError:
            raise ValueError(f"Invalid SiliconFlow {endpoint} JSON response") from None
        if not isinstance(result, dict):
            raise ValueError(f"Invalid SiliconFlow {endpoint} response")
        return result


class SiliconFlowEmbeddings(_SiliconFlowAPI, Embeddings):
    def __init__(
        self,
        api_key: str,
        model_name: str = "BAAI/bge-m3",
        base_url: str = "https://api.siliconflow.cn/v1",
        client: httpx.Client | None = None,
    ) -> None:
        super().__init__(api_key, base_url, client)
        self.model_name = model_name

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), 32):
            batch = texts[start : start + 32]
            result = self._post(
                "embeddings",
                {
                    "model": self.model_name,
                    "input": batch,
                    "encoding_format": "float",
                },
            )
            data = result.get("data")
            if not isinstance(data, list) or len(data) != len(batch):
                raise ValueError("Invalid embedding response: missing vectors")
            ordered: dict[int, list[float]] = {}
            for item in data:
                if not isinstance(item, dict):
                    raise ValueError("Invalid embedding response item")
                index, vector = item.get("index"), item.get("embedding")
                if type(index) is not int or not 0 <= index < len(batch) or index in ordered:
                    raise ValueError("Invalid embedding response index")
                if not isinstance(vector, list) or not vector:
                    raise ValueError("Invalid embedding vector")
                if any(
                    type(value) not in (int, float) or not math.isfinite(value) for value in vector
                ):
                    raise ValueError("Invalid embedding vector values")
                ordered[index] = [float(value) for value in vector]
            vectors.extend(ordered[index] for index in range(len(batch)))
        if vectors and any(len(vector) != len(vectors[0]) for vector in vectors):
            raise ValueError("Invalid embedding response: inconsistent dimensions")
        return vectors

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


class SiliconFlowReranker(_SiliconFlowAPI):
    def __init__(
        self,
        api_key: str,
        model_name: str = "BAAI/bge-reranker-v2-m3",
        base_url: str = "https://api.siliconflow.cn/v1",
        client: httpx.Client | None = None,
    ) -> None:
        super().__init__(api_key, base_url, client)
        self.model_name = model_name

    def rerank(
        self,
        query: str,
        documents: list[str],
        top_n: int,
    ) -> list[tuple[int, float]]:
        if not documents:
            return []
        result = self._post(
            "rerank",
            {
                "model": self.model_name,
                "query": query,
                "documents": documents,
                "top_n": min(top_n, len(documents)),
                "return_documents": False,
            },
        )
        results = result.get("results")
        if not isinstance(results, list) or not results or len(results) > top_n:
            raise ValueError("Invalid rerank response results")
        ranking: list[tuple[int, float]] = []
        seen: set[int] = set()
        for item in results:
            if not isinstance(item, dict):
                raise ValueError("Invalid rerank response item")
            index, score = item.get("index"), item.get("relevance_score")
            if type(index) is not int or not 0 <= index < len(documents) or index in seen:
                raise ValueError("Invalid rerank response index")
            if type(score) not in (float, int) or not math.isfinite(score):
                raise ValueError("Invalid rerank response score")
            ranking.append((index, float(score)))
            seen.add(index)
        return ranking
