"""限流：Redis 固定窗口计数。

选固定窗口而不是令牌桶：需求只有"别让一台机器把模型刷爆"，固定窗口两行代码、
误差最多窗口边界处的两倍，够用。要平滑限速再换滑动窗口。

三档按路径分桶，聊天最紧——它最贵（一次问答四次外部调用）。
"""

from __future__ import annotations

import time

from django.conf import settings
from django.core.cache import cache

CHAT = "chat"
WRITE = "write"
READ = "read"

WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def bucket_of(method: str, path: str) -> str:
    # 问答最贵，先判；其余写操作（含学生端反馈、运营接口）统一进 write 桶
    if "/chat/stream" in path or "/chat/turn" in path:
        return CHAT
    if method.upper() in WRITE_METHODS:
        return WRITE
    return READ


def limit_of(bucket: str) -> int:
    return {
        CHAT: settings.ACCESS_RATE_CHAT,
        WRITE: settings.ACCESS_RATE_WRITE,
        READ: settings.ACCESS_RATE_READ,
    }.get(bucket, settings.ACCESS_RATE_READ)


def hit(bucket: str, who: str) -> tuple[bool, int]:
    """返回 (是否放行, 剩余额度)。Redis 不可用时放行——限流不该把服务变不可用。"""
    window = int(time.time() // 60)
    key = f"acc:rl:{bucket}:{who}:{window}"
    limit = limit_of(bucket)
    try:
        client = cache.client.get_client(write=True)
        count = client.incr(key)
        if count == 1:
            client.expire(key, 70)      # 比窗口多 10s，避免边界处计数被提前清掉
    except Exception:  # noqa: BLE001
        return True, limit
    return count <= limit, max(0, limit - count)


def retry_after() -> int:
    """固定窗口：等到下一个整分钟即可。"""
    return max(1, 60 - int(time.time() % 60))
