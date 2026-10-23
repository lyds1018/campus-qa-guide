"""网关运维接口：只读。清理 / 重置类动作走命令行，不暴露到 HTTP。"""

from __future__ import annotations

from datetime import datetime

from django.conf import settings
from ninja import Router, Schema

from apps.gateway import breaker, meter
from apps.gateway import router as slot_router

router = Router(tags=["gw"])


class UsageRow(Schema):
    day: str
    task: str
    calls: int
    tokens: int
    cost: float
    cache_hits: int
    p50_ms: float
    p95_ms: float


class SlotState(Schema):
    state: str
    failures: int
    open_ttl: int | None = None


class ProvidersOut(Schema):
    slots: dict[str, SlotState]
    active_slots: list[str]
    models: dict[str, str]
    budget: dict


class CallOut(Schema):
    id: int
    trace_id: str
    task: str
    provider: str
    model: str
    status: str
    attempt: int
    cached: bool
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int
    cost: float
    error_code: str
    created_at: datetime


@router.get("/usage", response=list[UsageRow])
def usage(request, days: int = 7):
    return meter.usage(days=max(1, min(days, 90)))


@router.get("/providers", response=ProvidersOut)
def providers(request):
    active = slot_router.active_slots()
    snap = breaker.snapshot(slot_router.ALL_SLOTS)
    return ProvidersOut(
        slots={k: SlotState(**v) for k, v in snap.items()},
        active_slots=active,
        models={
            "main": settings.GW_CHAT_MAIN_MODEL,
            "fallback": settings.GW_CHAT_FALLBACK_MODEL,
            "aux": settings.GW_CHAT_AUX_MODEL,
            "embed": settings.GW_EMBED_MODEL,
            "rerank": settings.GW_RERANK_MODEL,
        },
        budget={
            "spent_today": meter.spent_today(),
            "daily_limit": settings.GW_DAILY_BUDGET_CNY,
            "hard_stop": settings.GW_BUDGET_HARD_STOP,
            "over": meter.over_budget(),
        },
    )


@router.get("/calls", response=list[CallOut])
def calls(request, status: str | None = None, limit: int = 20):
    return [
        CallOut(
            id=row.id,
            trace_id=str(row.trace_id),
            task=row.task,
            provider=row.provider,
            model=row.model,
            status=row.status,
            attempt=row.attempt,
            cached=row.cached,
            prompt_tokens=row.prompt_tokens,
            completion_tokens=row.completion_tokens,
            latency_ms=row.latency_ms,
            cost=float(row.cost),
            error_code=row.error_code,
            created_at=row.created_at,
        )
        for row in meter.recent(status=status, limit=limit)
    ]
