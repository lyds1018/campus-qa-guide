"""模型槽位覆盖：DB 优先，`.env` 兜底。

读路径带 30 秒缓存：运营改完立即 `invalidate()`，其他进程最多晚 30 秒生效——
比"改 .env 后重启"好得多，也不必为了一个模型名上配置中心。
"""

from __future__ import annotations

from django.core.cache import cache

KEY = "gw:model:overrides"
TTL = 30


def _load() -> dict[str, dict]:
    from apps.gateway.models import ModelSetting

    rows = ModelSetting.objects.filter(enabled=True)
    return {
        row.slot: {"base_url": row.base_url.strip(), "model": row.model.strip()}
        for row in rows
        if row.base_url.strip() or row.model.strip()
    }


def all_overrides() -> dict[str, dict]:
    cached = cache.get(KEY)
    if cached is not None:
        return cached
    try:
        data = _load()
    except Exception:  # noqa: BLE001  表还没建/库挂了都不该让问答不可用
        return {}
    cache.set(KEY, data, TTL)
    return data


def resolve(slot: str, base_url: str, model: str) -> tuple[str, str]:
    """槽位的实际 base_url / model。只覆盖非空项，留空表示沿用 .env。"""
    override = all_overrides().get(slot) or {}
    return override.get("base_url") or base_url, override.get("model") or model


def invalidate() -> None:
    cache.delete(KEY)
