"""Cohere 风格 rerank 适配器：POST /rerank，取 results[].relevance_score。"""

from __future__ import annotations

from django.conf import settings

from apps.gateway.base import RankedDoc, UpstreamBadRequest
from apps.gateway.providers.base import BaseAdapter

RERANK_PATH = "/rerank"


class RerankAdapter(BaseAdapter):
    task = "rerank"
    timeout_read = 20.0

    def __init__(self, *, slot: str, base_url: str, api_key: str, model: str):
        self.slot = slot
        self.base_url = base_url
        self.api_key = api_key
        self.model = model

    async def rerank(self, query: str, docs: list[str], top_k: int = 10) -> list[RankedDoc]:
        if not query or not docs:
            return []
        body = {
            "model": self.model,
            "query": query,
            "documents": docs,
            "top_n": min(top_k, len(docs)),
        }
        data = await self.post_json(
            RERANK_PATH, body, timeout=settings.GW_TIMEOUT_RERANK
        )
        results = data.get("results")
        if not isinstance(results, list):
            raise UpstreamBadRequest(f"{self.slot} rerank 响应缺少 results")

        ranked: list[RankedDoc] = []
        for item in results:
            idx = item.get("index")
            if not isinstance(idx, int) or not (0 <= idx < len(docs)):
                continue  # 越界下标直接丢，宁可少一条也不能错位
            ranked.append(
                RankedDoc(index=idx, score=float(item.get("relevance_score") or 0.0))
            )
        ranked.sort(key=lambda r: r.score, reverse=True)
        return ranked
