"""熔断：closed → open → half-open → closed。

按槽位（main / fallback / aux / embed / rerank）计数，全部状态存 Redis 并带 TTL，
不写任何清理逻辑——过期即恢复。
"""

from __future__ import annotations

from django.conf import settings
from django.core.cache import cache

CLOSED = "closed"
OPEN = "open"
HALF_OPEN = "half-open"


def _key(slot: str, part: str) -> str:
    return f"gw:cb:{slot}:{part}"


def _tripped_ttl() -> int:
    return max(600, settings.GW_BREAKER_COOLDOWN * 10)


def state(slot: str) -> str:
    if cache.get(_key(slot, "open")):
        return OPEN
    if cache.get(_key(slot, "tripped")):
        return HALF_OPEN
    return CLOSED


def allow(slot: str) -> bool:
    """是否放行。半开状态下只放一个探针，其余快速失败。"""
    current = state(slot)
    if current == OPEN:
        return False
    if current == HALF_OPEN:
        return bool(cache.add(_key(slot, "probe"), 1, settings.GW_BREAKER_COOLDOWN))
    return True


def record_success(slot: str) -> None:
    cache.delete(_key(slot, "fail"))
    if not cache.get(_key(slot, "tripped")):
        cache.delete(_key(slot, "ok"))
        return
    ok = (cache.get(_key(slot, "ok")) or 0) + 1
    cache.set(_key(slot, "ok"), ok, _tripped_ttl())
    if ok >= settings.GW_BREAKER_RECOVER:
        reset(slot)


def record_failure(slot: str) -> None:
    if cache.get(_key(slot, "tripped")):
        # 半开探针失败：重新打开并重置冷却
        cache.set(_key(slot, "open"), 1, settings.GW_BREAKER_COOLDOWN)
        cache.set(_key(slot, "tripped"), 1, _tripped_ttl())
        cache.delete(_key(slot, "probe"))
        cache.delete(_key(slot, "ok"))
        return

    key = _key(slot, "fail")
    try:
        count = cache.incr(key)
    except ValueError:  # key 不存在时 incr 抛 ValueError（django 各后端一致）
        cache.set(key, 1, settings.GW_BREAKER_WINDOW)
        count = 1
    if count >= settings.GW_BREAKER_THRESHOLD:
        cache.set(_key(slot, "open"), 1, settings.GW_BREAKER_COOLDOWN)
        cache.set(_key(slot, "tripped"), 1, _tripped_ttl())
        cache.delete(key)


def reset(slot: str) -> None:
    for part in ("fail", "open", "tripped", "probe", "ok"):
        cache.delete(_key(slot, part))


def snapshot(slots: list[str]) -> dict[str, dict]:
    ttl_fn = getattr(cache, "ttl", None)  # django-redis 有，LocMem 没有
    out: dict[str, dict] = {}
    for slot in slots:
        out[slot] = {
            "state": state(slot),
            "failures": cache.get(_key(slot, "fail")) or 0,
            "open_ttl": ttl_fn(_key(slot, "open")) if ttl_fn else None,
        }
    return out
