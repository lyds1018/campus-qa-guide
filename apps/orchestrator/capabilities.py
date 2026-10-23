"""能力调用适配层：给 P3 的入口套上超时与兜底。

P3 内部已经处理了"模型挂了"（回落原文出处），但那是**业务级**兜底。这一层防的是
另一类事：P3 自己抛异常、或一段卡住把整轮拖死。所有 P3 调用都必须从这里走，
否则编排层就没有统一的超时口径。
"""

from __future__ import annotations

import asyncio
import logging
from asyncio.exceptions import TimeoutError as AsyncTimeout
from collections.abc import AsyncIterator
from dataclasses import dataclass

from django.conf import settings

from apps.qa import prompts
from apps.qa.pipeline import qa
from apps.qa.types import Answer, QAEvent, Understanding

logger = logging.getLogger(__name__)

SERVICE_UNAVAILABLE = (
    "这段回答没能生成（{detail}）。可以稍后重试，或直接到学校网上办事大厅"
    "按事项名称查原文。"
)


@dataclass(frozen=True)
class TurnContext:
    question: str
    audience: str = "unknown"
    history: list[tuple[str, str]] | None = None
    doc_types: list[str] | None = None
    trace_id: str = ""


def failed_answer(ctx: TurnContext, detail: str) -> Answer:
    """P3 抛异常时的兜底答案。answerable=False，但 meta.failed 让上层能区别看待。"""
    return Answer(
        question=ctx.question,
        intent="",
        answerable=False,
        text=SERVICE_UNAVAILABLE.format(detail=detail),
        trace_id=ctx.trace_id,
        meta={"failed": True, "detail": detail},
    )


async def answer(
    ctx: TurnContext, understanding: Understanding | None = None
) -> Answer:
    try:
        return await asyncio.wait_for(
            qa.answer(
                ctx.question,
                audience=ctx.audience,
                history=ctx.history,
                doc_types=ctx.doc_types,
                trace_id=ctx.trace_id,
                understanding=understanding,
            ),
            timeout=settings.ORC_SEGMENT_TIMEOUT,
        )
    # 3.10 的 asyncio.TimeoutError 不是内置 TimeoutError 的子类，两个都要接；
    # 直接写 asyncio.TimeoutError 会被 ruff 的 UP041 改回内置名字，反而漏接
    except (AsyncTimeout, TimeoutError):
        logger.warning("段超时 question=%s", ctx.question[:40])
        return failed_answer(ctx, f"超时 {settings.ORC_SEGMENT_TIMEOUT:.0f}s")
    except Exception as exc:  # 编排层最后一道防线，宁可出一段兜底也不整轮 500
        logger.exception("段失败 question=%s", ctx.question[:40])
        return failed_answer(ctx, type(exc).__name__)


async def stream(
    ctx: TurnContext, understanding: Understanding | None = None
) -> AsyncIterator[QAEvent]:
    """真流式。异常在这里转成 error 事件，不向上抛——断流是产品的一部分。"""
    try:
        async for event in qa.answer_stream(
            ctx.question,
            audience=ctx.audience,
            history=ctx.history,
            doc_types=ctx.doc_types,
            trace_id=ctx.trace_id,
            understanding=understanding,
        ):
            yield event
    except Exception as exc:
        logger.exception("流式失败 question=%s", ctx.question[:40])
        yield QAEvent("error", detail=f"{type(exc).__name__}: {exc}")
        yield QAEvent("final", answer=failed_answer(ctx, type(exc).__name__))


def empty_answer(ctx: TurnContext) -> Answer:
    return Answer(
        question=ctx.question,
        intent="",
        answerable=False,
        text=prompts.EMPTY_QUESTION,
        trace_id=ctx.trace_id,
    )
