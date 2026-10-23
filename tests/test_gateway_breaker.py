"""熔断状态机：closed → open → half-open → closed。"""

from __future__ import annotations

import asyncio

import httpx
import pytest
import respx
from django.core.cache import cache

from apps.gateway import breaker
from apps.gateway.base import AllProvidersFailed, ChatMessage, ChatParams
from apps.gateway.gateway import Gateway
from apps.gateway.providers.base import reset_pool

BASE = "https://mock.test/v1"
URL = f"{BASE}/chat/completions"


@pytest.fixture(autouse=True)
def _isolate(settings):
    settings.GW_CHAT_MAIN_BASE_URL = BASE
    settings.GW_CHAT_MAIN_API_KEY = "test-key"
    settings.GW_CHAT_MAIN_MODEL = "mock-model"
    settings.GW_CHAT_FALLBACK_BASE_URL = ""
    settings.GW_CHAT_FALLBACK_API_KEY = ""
    settings.GW_RETRY_MAX = 1
    settings.GW_RETRY_INITIAL = 0.01
    settings.GW_CACHE_ENABLED = False
    settings.GW_FAULT_INJECTION = False
    settings.GW_BREAKER_THRESHOLD = 5
    settings.GW_BREAKER_WINDOW = 60
    settings.GW_BREAKER_COOLDOWN = 60
    settings.GW_BREAKER_RECOVER = 2
    settings.CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "gw-breaker-test",
        }
    }
    cache.clear()
    reset_pool()
    breaker.reset("main")
    yield
    cache.clear()
    reset_pool()


def _chat():
    return asyncio.run(
        Gateway().chat([ChatMessage("user", "hi")], params=ChatParams(temperature=0.9))
    )


def _trip(slot: str = "main", times: int = 5) -> None:
    for _ in range(times):
        breaker.record_failure(slot)


def test_opens_after_threshold_failures():
    for i in range(4):
        breaker.record_failure("main")
        assert breaker.state("main") == breaker.CLOSED, f"第 {i + 1} 次不该打开"

    breaker.record_failure("main")
    assert breaker.state("main") == breaker.OPEN
    assert breaker.allow("main") is False


def test_half_open_only_lets_one_probe():
    _trip()
    # 模拟冷却到期：open 键过期，但 tripped 还在
    cache.delete("gw:cb:main:open")
    assert breaker.state("main") == breaker.HALF_OPEN

    assert breaker.allow("main") is True
    assert breaker.allow("main") is False  # 第二个请求被挡住


def test_half_open_success_closes():
    _trip()
    cache.delete("gw:cb:main:open")

    breaker.record_success("main")
    assert breaker.state("main") == breaker.HALF_OPEN  # 才 1 次
    breaker.record_success("main")
    assert breaker.state("main") == breaker.CLOSED


def test_half_open_failure_reopens():
    _trip()
    cache.delete("gw:cb:main:open")
    assert breaker.allow("main") is True

    breaker.record_failure("main")
    assert breaker.state("main") == breaker.OPEN


def test_reset_clears_everything():
    _trip()
    breaker.reset("main")
    assert breaker.state("main") == breaker.CLOSED
    assert breaker.allow("main") is True


@respx.mock
def test_open_circuit_skips_http():
    """熔断打开时一个请求都不该发出去。"""
    route = respx.post(URL).mock(return_value=httpx.Response(500, text="down"))
    _trip()
    assert breaker.state("main") == breaker.OPEN

    with pytest.raises(AllProvidersFailed) as err:
        _chat()

    assert route.call_count == 0
    assert err.value.errors[0] == ("main", "CircuitOpen")


@respx.mock
def test_failure_from_http_trips_breaker(settings):
    respx.post(URL).mock(return_value=httpx.Response(500, text="down"))

    for _ in range(settings.GW_BREAKER_THRESHOLD):
        with pytest.raises(AllProvidersFailed):
            _chat()

    assert breaker.state("main") == breaker.OPEN
