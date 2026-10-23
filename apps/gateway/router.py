"""槽位装配与降级链。

槽位与供应商是一对一：一个槽位 = 一个 base_url + 一把 key + 一个模型。
换厂只改 .env，代码里不出现任何厂商品牌名。
"""

from __future__ import annotations

from typing import Literal

from django.conf import settings

from apps.gateway import overrides
from apps.gateway.base import (
    ChatAdapter,
    EmbedAdapter,
    NotConfigured,
    RerankAdapter,
)
from apps.gateway.providers.openai_compat import OpenAICompatAdapter
from apps.gateway.providers.rerank import RerankAdapter as CohereRerankAdapter

Role = Literal["main", "aux"]

ALL_SLOTS = ["main", "fallback", "aux", "embed", "rerank"]


def _chat_adapter(slot: str, base_url: str, api_key: str, model: str) -> ChatAdapter | None:
    # 运营侧覆盖（P6）在这里生效：base_url / model 可换，key 只认 .env
    base_url, model = overrides.resolve(slot, base_url, model)
    if not (base_url and api_key and model):
        return None
    return OpenAICompatAdapter(slot=slot, base_url=base_url, api_key=api_key, model=model)


def main_adapter() -> ChatAdapter:
    adapter = _chat_adapter(
        "main",
        settings.GW_CHAT_MAIN_BASE_URL,
        settings.GW_CHAT_MAIN_API_KEY,
        settings.GW_CHAT_MAIN_MODEL,
    )
    if adapter is None:
        raise NotConfigured("GW_CHAT_MAIN_* 未配置，chat 不可用")
    return adapter


def fallback_adapter() -> ChatAdapter | None:
    return _chat_adapter(
        "fallback",
        settings.GW_CHAT_FALLBACK_BASE_URL,
        settings.GW_CHAT_FALLBACK_API_KEY,
        settings.GW_CHAT_FALLBACK_MODEL,
    )


def aux_adapter() -> ChatAdapter | None:
    return _chat_adapter(
        "aux",
        settings.GW_CHAT_AUX_BASE_URL,
        settings.GW_CHAT_AUX_API_KEY,
        settings.GW_CHAT_AUX_MODEL,
    )


def chat_chain(role: Role = "main") -> list[ChatAdapter]:
    """降级链：aux 缺配置时退回 main；main 永远在链尾兜底。"""
    main = main_adapter()
    if role == "aux":
        aux = aux_adapter()
        return [aux, main] if aux else [main]
    chain: list[ChatAdapter] = [main]
    fallback = fallback_adapter()
    if fallback:
        chain.append(fallback)
    return chain


def embed_adapter() -> EmbedAdapter:
    """embedding 只有一条路：向量与模型强绑定，不做运行期降级。"""
    base_url, model = overrides.resolve(
        "embed", settings.GW_EMBED_BASE_URL, settings.GW_EMBED_MODEL
    )
    if not (base_url and settings.GW_EMBED_API_KEY):
        raise NotConfigured("GW_EMBED_* 未配置，向量相关能力不可用")
    return OpenAICompatAdapter(
        slot="embed",
        base_url=base_url,
        api_key=settings.GW_EMBED_API_KEY,
        model=model,
        doc_prefix=settings.GW_EMBED_DOC_PREFIX,
        query_prefix=settings.GW_EMBED_QUERY_PREFIX,
    )


def rerank_adapter() -> RerankAdapter | None:
    """未配置返回 None，调用方按"不重排"降级，不算故障。"""
    base_url, model = overrides.resolve(
        "rerank", settings.GW_RERANK_BASE_URL, settings.GW_RERANK_MODEL
    )
    if not (base_url and settings.GW_RERANK_API_KEY):
        return None
    return CohereRerankAdapter(
        slot="rerank",
        base_url=base_url,
        api_key=settings.GW_RERANK_API_KEY,
        model=model,
    )


def active_slots() -> list[str]:
    """实际配置了的槽位，供 gw_probe / providers 接口展示。"""
    slots = []
    if settings.GW_CHAT_MAIN_BASE_URL and settings.GW_CHAT_MAIN_API_KEY:
        slots.append("main")
    if settings.GW_CHAT_FALLBACK_BASE_URL and settings.GW_CHAT_FALLBACK_API_KEY:
        slots.append("fallback")
    if settings.GW_CHAT_AUX_BASE_URL and settings.GW_CHAT_AUX_API_KEY:
        slots.append("aux")
    if settings.GW_EMBED_BASE_URL and settings.GW_EMBED_API_KEY:
        slots.append("embed")
    if settings.GW_RERANK_BASE_URL and settings.GW_RERANK_API_KEY:
        slots.append("rerank")
    return slots
