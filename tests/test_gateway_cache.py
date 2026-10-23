"""缓存：精确命中、指纹失效、高温不缓存、占位向量缓存、流式回放。"""

from __future__ import annotations

import asyncio

import httpx
import pytest
import respx
from django.core.cache import cache

from apps.gateway import cache as gw_cache
from apps.gateway.base import ChatMessage, ChatParams
from apps.gateway.gateway import Gateway
from apps.gateway.providers.base import reset_pool

BASE = "https://mock.test/v1"
CHAT_URL = f"{BASE}/chat/completions"
EMBED_URL = f"{BASE}/embeddings"
DIM = 1024


def ok_body(text: str = "去教务处补办") -> dict:
    return {
        "model": "mock-model",
        "choices": [
            {"message": {"role": "assistant", "content": text}, "finish_reason": "stop"}
        ],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20},
    }


@pytest.fixture(autouse=True)
def _isolate(settings, monkeypatch):
    settings.GW_CHAT_MAIN_BASE_URL = BASE
    settings.GW_CHAT_MAIN_API_KEY = "test-key"
    settings.GW_CHAT_MAIN_MODEL = "mock-model"
    settings.GW_CHAT_FALLBACK_BASE_URL = ""
    settings.GW_CHAT_FALLBACK_API_KEY = ""
    settings.GW_EMBED_BASE_URL = BASE
    settings.GW_EMBED_API_KEY = "test-key"
    settings.GW_EMBED_MODEL = "mock-embed"
    settings.GW_EMBED_DOC_PREFIX = ""
    settings.GW_EMBED_QUERY_PREFIX = ""
    settings.GW_RERANK_BASE_URL = ""
    settings.GW_RERANK_API_KEY = ""
    settings.GW_RETRY_MAX = 1
    settings.GW_CACHE_ENABLED = True
    settings.GW_CACHE_TTL_CHAT = 3600
    settings.GW_CACHE_TTL_EMBED = 3600
    settings.GW_FAULT_INJECTION = False
    settings.GW_DAILY_BUDGET_CNY = 10_000
    settings.CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "gw-cache-test",
        }
    }
    monkeypatch.setattr(gw_cache, "kb_fingerprint", lambda: "fp-v1")
    cache.clear()
    reset_pool()
    yield
    cache.clear()
    reset_pool()


def _ask(temperature: float = 0.0):
    return asyncio.run(
        Gateway().chat(
            [ChatMessage("user", "学生证丢了怎么办")], params=ChatParams(temperature=temperature)
        )
    )


@respx.mock
def test_second_call_hits_cache():
    route = respx.post(CHAT_URL).mock(return_value=httpx.Response(200, json=ok_body()))

    first = _ask()
    second = _ask()

    assert route.call_count == 1
    assert first.cached is False
    assert second.cached is True
    assert second.text == first.text


@respx.mock
def test_fingerprint_change_invalidates(monkeypatch):
    route = respx.post(CHAT_URL).mock(return_value=httpx.Response(200, json=ok_body()))
    _ask()

    monkeypatch.setattr(gw_cache, "kb_fingerprint", lambda: "fp-v2")
    second = _ask()

    assert route.call_count == 2
    assert second.cached is False


@respx.mock
def test_high_temperature_is_not_cached():
    route = respx.post(CHAT_URL).mock(return_value=httpx.Response(200, json=ok_body()))

    _ask(temperature=0.9)
    _ask(temperature=0.9)

    assert route.call_count == 2


@respx.mock
def test_embedding_cache_returns_identical_vectors():
    vec = [0.01] * DIM
    route = respx.post(EMBED_URL).mock(
        return_value=httpx.Response(
            200,
            json={"model": "mock-embed", "data": [{"index": 0, "embedding": vec}],
                  "usage": {"prompt_tokens": 8}},
        )
    )

    first = asyncio.run(Gateway().embed(["学生证补办"]))
    second = asyncio.run(Gateway().embed(["学生证补办"]))

    assert route.call_count == 1
    assert first == second
    assert len(first[0]) == DIM


@respx.mock
def test_embedding_reorders_by_index():
    """供应商不保证顺序：返回倒序也要按 index 归位。"""
    a, b = [0.1] * DIM, [0.2] * DIM
    respx.post(EMBED_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "model": "mock-embed",
                "data": [{"index": 1, "embedding": b}, {"index": 0, "embedding": a}],
                "usage": {"prompt_tokens": 8},
            },
        )
    )

    out = asyncio.run(Gateway().embed(["第一段", "第二段"]))
    assert out[0] == a
    assert out[1] == b


@respx.mock
def test_embedding_dimension_mismatch_rejected():
    from apps.gateway.base import AllProvidersFailed, DimensionMismatch

    respx.post(EMBED_URL).mock(
        return_value=httpx.Response(
            200,
            json={"model": "mock-embed", "data": [{"index": 0, "embedding": [0.1] * 8}],
                  "usage": {"prompt_tokens": 8}},
        )
    )

    with pytest.raises((DimensionMismatch, AllProvidersFailed)):
        asyncio.run(Gateway().embed(["x"]))


@respx.mock
def test_stream_cache_replays():
    sse = (
        'data: {"model":"mock-model","choices":[{"delta":{"content":"去"}}]}\n\n'
        'data: {"model":"mock-model","choices":[{"delta":{"content":"教务处"}}]}\n\n'
        'data: {"model":"mock-model","choices":[{"delta":{},"finish_reason":"stop"}],'
        '"usage":{"prompt_tokens":10,"completion_tokens":4}}\n\n'
        "data: [DONE]\n\n"
    )
    route = respx.post(CHAT_URL).mock(return_value=httpx.Response(200, text=sse))

    async def collect():
        gw = Gateway()
        out = [d.text async for d in gw.chat_stream([ChatMessage("user", "x")])]
        return "".join(out)

    first = asyncio.run(collect())
    second = asyncio.run(collect())

    assert first == "去教务处"
    assert second == first  # 命中缓存回放，内容一致
    assert route.call_count == 1
