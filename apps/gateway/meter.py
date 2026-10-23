"""调用台账：成本计算、进程内缓冲批量落库、当日预算护栏、汇总查询。

台账不是事实源，所以宁可丢一批也不阻塞主链路：缓冲满 50 条或距上次落库超 5 秒才写。
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import date
from decimal import Decimal

from django.conf import settings
from django.core.cache import cache
from django.db import connection

from apps.gateway.models import AICall, CallStatus

logger = logging.getLogger(__name__)

# 元 / 百万 token（输入，输出）。占位值：P2 完成时按供应商当期价目表校准。
MODEL_PRICING: dict[str, tuple[float, float]] = {
    "deepseek-chat": (2.0, 8.0),
    "deepseek-flash": (2.0, 8.0),
    "qwen-plus": (0.8, 2.0),
    "qwen-flash": (0.15, 1.5),
    "qwen-turbo": (0.3, 0.6),
    "Qwen/Qwen2.5-7B-Instruct": (0.35, 0.35),
    "BAAI/bge-m3": (0.5, 0.0),
    "BAAI/bge-reranker-v2-m3": (0.5, 0.0),
}

BATCH_SIZE = 50
FLUSH_INTERVAL = 5.0

_buffer: list[AICall] = []
_last_flush = time.monotonic()
# 预算按微元（0.000001 元）累计：Redis 只支持整数自增，用毫元会把单次探活的花费截成 0
_MICRO = 1_000_000


def cost_of(model: str, prompt_tokens: int, completion_tokens: int) -> Decimal:
    p_in, p_out = MODEL_PRICING.get(model, (0.0, 0.0))
    amount = (
        Decimal(str(p_in)) * prompt_tokens / Decimal(1_000_000)
        + Decimal(str(p_out)) * completion_tokens / Decimal(1_000_000)
    )
    return amount.quantize(Decimal("0.000001"))


def record(
    *,
    trace_id,
    task: str,
    provider: str,
    model: str,
    status: str = CallStatus.OK,
    attempt: int = 1,
    cached: bool = False,
    stream: bool = False,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    latency_ms: int = 0,
    first_token_ms: int | None = None,
    error: BaseException | None = None,
    meta: dict | None = None,
) -> None:
    """只入缓冲，不做 IO。错误信息截断 500 字，避免错误体整段 prompt 落库。"""
    row = AICall(
        trace_id=trace_id,
        task=task,
        provider=provider,
        model=model,
        status=status,
        attempt=attempt,
        cached=cached,
        stream=stream,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        latency_ms=max(0, latency_ms),
        first_token_ms=first_token_ms,
        cost=Decimal("0") if cached else cost_of(model, prompt_tokens, completion_tokens),
        error_code=type(error).__name__ if error else "",
        error_msg=str(error)[:500] if error else "",
        meta=meta or {},
    )
    _buffer.append(row)
    if not cached and row.cost:
        try:
            add_spend(row.cost)
        except Exception:  # noqa: BLE001
            logger.warning("预算计数失败，忽略本条", exc_info=True)


async def maybe_flush() -> None:
    global _last_flush
    if not _buffer:
        return
    if len(_buffer) < BATCH_SIZE and time.monotonic() - _last_flush < FLUSH_INTERVAL:
        return
    await asyncio.to_thread(flush_sync)


def flush_sync() -> int:
    """同步落库。async 上下文里必须经 asyncio.to_thread 调用（ORM 是同步的）。"""
    global _last_flush
    if not _buffer:
        _last_flush = time.monotonic()
        return 0
    batch = _buffer[:]
    _buffer.clear()
    _last_flush = time.monotonic()
    try:
        AICall.objects.bulk_create(batch, batch_size=500)
    except Exception:  # noqa: BLE001
        # 台账不是事实源：写不进去就丢这一批。让记账失败把已经生成的答案 500 掉，
        # 是最典型的"监控把业务搞挂"。
        logger.exception("ai_calls 落库失败，丢弃 %d 条", len(batch))
        return 0
    return len(batch)


def pending() -> int:
    return len(_buffer)


def reset() -> None:
    """丢弃缓冲并重置计时。

    进程内缓冲是全局的：跨用例残留会让下一个用例在"距上次 flush 已超 5 秒"时
    触发落库，而没打 django_db 标记的用例一律报 Database access not allowed。
    只在测试的隔离夹具里调用，运行期不要碰。
    """
    global _last_flush
    _buffer.clear()
    _last_flush = time.monotonic()


# --------------------------------------------------------------- 预算护栏


def _budget_key() -> str:
    return f"gw:budget:{date.today().isoformat()}"


def add_spend(amount: Decimal) -> None:
    key = _budget_key()
    micro = int(amount * _MICRO)
    if micro <= 0:
        return
    try:
        cache.incr(key, micro)
    except ValueError:
        cache.set(key, micro, 60 * 60 * 30)


def spent_today() -> float:
    return (cache.get(_budget_key()) or 0) / _MICRO


def over_budget() -> bool:
    return spent_today() >= float(settings.GW_DAILY_BUDGET_CNY)


def budget_hard_stop() -> bool:
    return settings.GW_BUDGET_HARD_STOP and spent_today() >= 2 * float(
        settings.GW_DAILY_BUDGET_CNY
    )


# --------------------------------------------------------------- 汇总查询


def usage(days: int = 7) -> list[dict]:
    sql = """
        SELECT date_trunc('day', created_at)::date AS day,
               task,
               count(*) AS calls,
               coalesce(sum(prompt_tokens + completion_tokens), 0) AS tokens,
               coalesce(sum(cost), 0) AS cost,
               count(*) FILTER (WHERE cached) AS cache_hits,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms) AS p50,
               percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms) AS p95
        FROM ai_calls
        WHERE created_at >= now() - make_interval(days => %s)
        GROUP BY 1, 2
        ORDER BY 1 DESC, 2
    """
    with connection.cursor() as cur:
        cur.execute(sql, [max(1, days)])
        rows = cur.fetchall()
    return [
        {
            "day": row[0].isoformat(),
            "task": row[1],
            "calls": row[2],
            "tokens": int(row[3]),
            "cost": float(row[4]),
            "cache_hits": row[5],
            "p50_ms": round(float(row[6] or 0), 1),
            "p95_ms": round(float(row[7] or 0), 1),
        }
        for row in rows
    ]


def recent(status: str | None = None, limit: int = 20) -> list[AICall]:
    qs = AICall.objects.all()
    if status:
        qs = qs.filter(status=status)
    return list(qs[: max(1, min(limit, 200))])
