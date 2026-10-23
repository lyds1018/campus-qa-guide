"""三级缓存 + 知识指纹。

L1 chat 精确缓存（key 含知识指纹）｜ L2 向量缓存 ｜ L3 重排缓存。
chat 不做语义相似匹配：同一问句在知识换版 / 不同身份下答案本就不同。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict

from django.conf import settings
from django.core.cache import cache
from django.db.models import Count, Max

from apps.gateway.base import ChatMessage, ChatParams

PREFIX = "gw:cache"
FINGERPRINT_KEY = "gw:kb:fingerprint"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def kb_fingerprint() -> str:
    """published 文档数 + 最新发布时间。知识发布 / 回滚后由 P6 主动删除该键。"""
    cached = cache.get(FINGERPRINT_KEY)
    if cached:
        return str(cached)

    from apps.knowledge.models import Document, PublishStatus

    agg = Document.objects.filter(status=PublishStatus.PUBLISHED).aggregate(
        n=Count("id"), latest=Max("published_at")
    )
    latest = agg["latest"].isoformat() if agg["latest"] else "-"
    fp = _sha(f"{agg['n']}:{latest}")[:16]
    cache.set(FINGERPRINT_KEY, fp, settings.GW_KB_FINGERPRINT_TTL)
    return fp


def chat_key(model: str, messages: list[ChatMessage], params: ChatParams, fingerprint: str) -> str:
    """fingerprint 由调用方先取好并在同一请求内复用，避免每个 key 都查一次库。"""
    body = {
        "messages": [m.as_dict() for m in messages],
        "params": asdict(params),
        "kb": fingerprint,
    }
    raw = json.dumps(body, ensure_ascii=False, sort_keys=True)
    return f"{PREFIX}:l1:{model}:{_sha(raw)}"


def embed_key(model: str, kind: str, text: str) -> str:
    digest = _sha(kind + "\x00" + text)
    return f"{PREFIX}:l2:{model}:{digest}"


def rerank_key(model: str, query: str, docs: list[str]) -> str:
    digest = _sha(query + "\x00" + "\x00".join(docs))
    return f"{PREFIX}:l3:{model}:{digest}"


def get(key: str):
    return cache.get(key)


def put(key: str, value, ttl: int) -> None:
    cache.set(key, value, ttl)


def clear() -> int:
    """清空网关缓存，不动熔断状态。返回删除条数（后端不支持时为 0）。"""
    pattern = f"{PREFIX}:*"
    try:
        return int(cache.delete_pattern(pattern))
    except (AttributeError, NotImplementedError):  # LocMem 等后端没有 delete_pattern
        return 0
