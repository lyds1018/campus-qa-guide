"""重试与错误归一：respx 在 HTTP 层 mock，不依赖真实供应商。"""

from __future__ import annotations

import asyncio

import httpx
import pytest
import respx
from django.core.cache import cache

from apps.gateway.base import AllProvidersFailed, ChatMessage, ChatParams
from apps.gateway.gateway import Gateway
from apps.gateway.providers.base import reset_pool

BASE = "https://mock.test/v1"
URL = f"{BASE}/chat/completions"


def ok_body(text: str = "好的") -> dict:
    return {
        "model": "mock-model",
        "choices": [
            {"message": {"role": "assistant", "content": text}, "finish_reason": "stop"}
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }


@pytest.fixture(autouse=True)
def _isolate(settings):
    settings.GW_CHAT_MAIN_BASE_URL = BASE
    settings.GW_CHAT_MAIN_API_KEY = "test-key"
    settings.GW_CHAT_MAIN_MODEL = "mock-model"
    settings.GW_CHAT_FALLBACK_BASE_URL = ""
    settings.GW_CHAT_FALLBACK_API_KEY = ""
    settings.GW_CHAT_AUX_BASE_URL = ""
    settings.GW_CHAT_AUX_API_KEY = ""
    settings.GW_RETRY_MAX = 3
    settings.GW_RETRY_INITIAL = 0.01
    settings.GW_CACHE_ENABLED = False
    settings.GW_FAULT_INJECTION = False
    settings.GW_DAILY_BUDGET_CNY = 10_000
    settings.CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "gw-retry-test",
        }
    }
    cache.clear()
    reset_pool()
    yield
    cache.clear()
    reset_pool()


def _chat(gw: Gateway):
    return gw.chat([ChatMessage("user", "你好")], params=ChatParams(temperature=0.9))


@respx.mock
def test_retries_5xx_then_succeeds():
    route = respx.post(URL).mock(
        side_effect=[
            httpx.Response(500, text="boom"),
            httpx.Response(502, text="bad gateway"),
            httpx.Response(200, json=ok_body()),
        ]
    )
    result = asyncio.run(_chat(Gateway()))

    assert result.text == "好的"
    assert route.call_count == 3


@respx.mock
def test_gives_up_after_max_attempts():
    route = respx.post(URL).mock(return_value=httpx.Response(503, text="down"))
    with pytest.raises(AllProvidersFailed) as err:
        asyncio.run(_chat(Gateway()))

    assert route.call_count == 3  # GW_RETRY_MAX
    assert err.value.errors[0][0] == "main"
    assert err.value.errors[0][1] == "UpstreamServerError"


@respx.mock
def test_400_is_not_retried():
    route = respx.post(URL).mock(return_value=httpx.Response(400, text="bad request"))
    with pytest.raises(AllProvidersFailed) as err:
        asyncio.run(_chat(Gateway()))

    assert route.call_count == 1
    assert err.value.errors[0][1] == "UpstreamBadRequest"


@respx.mock
def test_long_retry_after_skips_retry():
    """429 带 30s Retry-After：等它不如换一家，直接失败不重试。"""
    route = respx.post(URL).mock(
        return_value=httpx.Response(429, text="rate limited", headers={"Retry-After": "30"})
    )
    with pytest.raises(AllProvidersFailed):
        asyncio.run(_chat(Gateway()))

    assert route.call_count == 1


@respx.mock
def test_short_retry_after_is_retried():
    route = respx.post(URL).mock(
        side_effect=[
            httpx.Response(429, text="slow down", headers={"Retry-After": "1"}),
            httpx.Response(200, json=ok_body()),
        ]
    )
    result = asyncio.run(_chat(Gateway()))

    assert result.text == "好的"
    assert route.call_count == 2


@respx.mock
def test_content_filter_maps_to_blocked():
    body = ok_body()
    body["choices"][0]["finish_reason"] = "content_filter"
    respx.post(URL).mock(return_value=httpx.Response(200, json=body))

    with pytest.raises(AllProvidersFailed) as err:
        asyncio.run(_chat(Gateway()))

    assert err.value.errors[0][1] == "ContentBlocked"
