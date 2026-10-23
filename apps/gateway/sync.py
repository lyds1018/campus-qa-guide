"""同步入口。给 management command 用；async 上下文里调用 run() 是写错了，直接抛。

示例：
    from apps.gateway.sync import run
    vectors = run(gateway.embed(texts))
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from typing import TypeVar

from apps.gateway.base import GatewayError

T = TypeVar("T")


def run(coro: Awaitable[T]) -> T:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)  # type: ignore[arg-type]
    raise GatewayError("已在事件循环内，请直接 await，不要用 run()")
