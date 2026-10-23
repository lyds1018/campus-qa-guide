"""台账：成本计算、批量落库、预算护栏、汇总查询。"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from django.core.cache import cache

from apps.gateway import meter
from apps.gateway.models import AICall


@pytest.fixture(autouse=True)
def _isolate(settings):
    settings.GW_DAILY_BUDGET_CNY = 1.0
    settings.GW_BUDGET_HARD_STOP = False
    settings.CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "gw-meter-test",
        }
    }
    cache.clear()
    meter._buffer.clear()
    yield
    cache.clear()
    meter._buffer.clear()


def _record(**kwargs):
    params = {
        "trace_id": str(uuid.uuid4()),
        "task": "chat",
        "provider": "main",
        "model": "deepseek-chat",
        "prompt_tokens": 1000,
        "completion_tokens": 500,
        "latency_ms": 800,
    }
    params.update(kwargs)
    meter.record(**params)


def test_cost_of_is_per_million():
    # 1000 输入 × ¥2/M + 500 输出 × ¥8/M = 0.002 + 0.004
    assert meter.cost_of("deepseek-chat", 1000, 500) == Decimal("0.006000")


def test_unknown_model_costs_nothing():
    assert meter.cost_of("some-unlisted-model", 9999, 9999) == Decimal("0.000000")


def test_cached_row_is_free():
    _record(cached=True)
    row = meter._buffer[0]
    assert row.cost == Decimal("0")
    assert meter.spent_today() == 0.0  # 命中缓存不占预算


def test_injected_provider_error_is_truncated():
    _record(error=RuntimeError("x" * 900))
    row = meter._buffer[0]
    assert row.error_code == "RuntimeError"
    assert len(row.error_msg) == 500


@pytest.mark.django_db(transaction=True)
def test_flush_persists_and_clears():
    _record()
    _record(provider="fallback", status="degraded")
    assert meter.pending() == 2

    flushed = meter.flush_sync()

    assert flushed == 2
    assert meter.pending() == 0
    assert AICall.objects.count() == 2
    assert AICall.objects.filter(status="degraded").count() == 1


@pytest.mark.django_db(transaction=True)
def test_usage_aggregates_by_day_and_task():
    _record()
    _record(task="embedding", provider="embed", completion_tokens=0)
    meter.flush_sync()

    rows = meter.usage(days=1)

    tasks = {row["task"] for row in rows}
    assert tasks == {"chat", "embedding"}
    chat_row = next(r for r in rows if r["task"] == "chat")
    assert chat_row["calls"] == 1
    assert chat_row["tokens"] == 1500
    assert chat_row["cost"] == pytest.approx(0.006, abs=1e-6)


def test_budget_guard_flips_over():
    assert meter.over_budget() is False

    meter.add_spend(Decimal("0.6"))
    assert meter.spent_today() == pytest.approx(0.6)
    assert meter.over_budget() is False

    meter.add_spend(Decimal("0.5"))
    assert meter.over_budget() is True


def test_hard_stop_needs_flag_and_double_budget(settings):
    settings.GW_BUDGET_HARD_STOP = False
    meter.add_spend(Decimal("3"))
    assert meter.budget_hard_stop() is False

    settings.GW_BUDGET_HARD_STOP = True
    assert meter.budget_hard_stop() is True


@pytest.mark.django_db
def test_flush_failure_does_not_break_business(monkeypatch):
    """台账不是事实源：落库失败要吞掉，不能让已经生成的答案 500。"""
    import uuid

    from apps.gateway import meter

    meter.record(
        trace_id=uuid.uuid4(),
        task="chat",
        provider="main",
        model="deepseek-chat",
        prompt_tokens=10,
        completion_tokens=5,
    )
    assert meter.pending() == 1

    class _Broken:
        def bulk_create(self, *args, **kwargs):
            raise RuntimeError("db down")

    class _FakeAICall:
        objects = _Broken()

    monkeypatch.setattr(meter, "AICall", _FakeAICall)
    assert meter.flush_sync() == 0
    assert meter.pending() == 0          # 这批丢了，但不阻塞，也不重试
