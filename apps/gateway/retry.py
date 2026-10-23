"""重试：只对幂等安全的错误重试，退避带抖动。

tenacity 的 retry 谓词接管"该不该重试"，重试次数与退避来自 settings。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TypeVar

from django.conf import settings
from tenacity import (
    AsyncRetrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from apps.gateway.base import UpstreamRateLimited, UpstreamServerError, UpstreamTimeout

T = TypeVar("T")

RETRY_AFTER_LIMIT = 10.0


def should_retry(exc: BaseException) -> bool:
    """429 带长 Retry-After 时不重试——等 10 秒不如直接换一家。"""
    if isinstance(exc, UpstreamRateLimited):
        return exc.retry_after is None or exc.retry_after <= RETRY_AFTER_LIMIT
    return isinstance(exc, UpstreamTimeout | UpstreamServerError)


async def call_with_retry(
    fn: Callable[[int], Awaitable[T]], tracker: dict | None = None
) -> T:
    """fn 收到第几次尝试（从 1 开始），返回值原样透出。

    tracker 是调用方传进来的可变容器，成功与失败都会写入实际尝试次数，
    供台账记录"这次调用花了几次"。
    """
    retrying = AsyncRetrying(
        stop=stop_after_attempt(settings.GW_RETRY_MAX),
        wait=wait_exponential_jitter(
            multiplier=settings.GW_RETRY_INITIAL, max=8, jitter=0.3
        ),
        retry=retry_if_exception(should_retry),
        reraise=True,  # 抛原异常：包成 RetryError 后降级链分不清是超时还是 400
    )
    async for attempt in retrying:
        with attempt:
            number = attempt.retry_state.attempt_number
            if tracker is not None:
                tracker["attempt"] = number
            return await fn(number)
    raise RuntimeError("unreachable")  # pragma: no cover
