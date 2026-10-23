"""SSE 事件协议（P4 定义，P5 出口）。

帧格式就是 SSE 最小集：一个 `event:` 行 + 一个 `data:` 行 + 空行。不用 `id:`（不做
断线补发，重连靠前端重新发问），也不用 `retry:`（浏览器默认 3s 足够）。

心跳用注释行 `: ping`，浏览器与代理都会忽略，但能挡住 Nginx 的 60s 空闲断开。
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from django.conf import settings

SESSION = "session"    # 会话与轮次：本轮属于哪个 conversation_id / turn
STAGE = "stage"        # 进度：understand / route / fanout / generate
DELTA = "delta"        # 增量文本
ANSWER = "answer"      # 整轮结果（装配后的 TurnResult）
NOTICE = "notice"      # 非致命提示（降级、部分失败、口径冲突）
ERROR = "error"        # 致命错误；随后仍会收到 done
DONE = "done"          # 收尾：turn、耗时、trace_id

HEARTBEAT = ": ping\n\n"


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def session_frame(conversation_id: str, turn: int) -> str:
    return sse(SESSION, {"conversation_id": conversation_id, "turn": turn})


def stage_frame(stage: str, **extra) -> str:
    return sse(STAGE, {"stage": stage, **extra})


async def with_heartbeat(
    frames: AsyncIterator[str], interval: float | None = None
) -> AsyncIterator[str]:
    """等上游太久就插入心跳，避免长静默被代理断开。

    `__anext__` 包成 Task 才能用 `asyncio.wait` 加超时；取消时把挂起的 Task 一起收掉，
    否则生成器不会关闭、数据库连接会挂着。
    """
    interval = interval or settings.ORC_HEARTBEAT
    iterator = frames.__aiter__()
    pending: asyncio.Task | None = asyncio.ensure_future(iterator.__anext__())
    try:
        while True:
            done, _ = await asyncio.wait({pending}, timeout=interval)
            if not done:
                yield HEARTBEAT
                continue
            try:
                chunk = pending.result()
            except StopAsyncIteration:
                return
            yield chunk
            pending = asyncio.ensure_future(iterator.__anext__())
    finally:
        if pending is not None and not pending.done():
            pending.cancel()
        aclose = getattr(iterator, "aclose", None)
        if aclose is not None:
            await aclose()
