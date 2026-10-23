"""网关门面。P3 只需 from apps.gateway.gateway import gateway。

职责只有四件：走缓存、选槽位、兜可靠性、记一笔账。不碰业务语义。
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import replace
from typing import Literal, TypeVar

from django.conf import settings
from pydantic import BaseModel, ValidationError

from apps.gateway import breaker, cache, meter, retry, router
from apps.gateway.base import (
    AllProvidersFailed,
    ChatDelta,
    ChatMessage,
    ChatParams,
    ChatResult,
    ContentBlocked,
    DimensionMismatch,
    GatewayError,
    RankedDoc,
    StreamInterrupted,
    UpstreamBadRequest,
    UpstreamTimeout,
)
from apps.gateway.models import CallStatus, CallTask

T = TypeVar("T", bound=BaseModel)

EMBED_BATCH = 64
REPLAY_CHUNK = 32


def _new_trace_id() -> str:
    return str(uuid.uuid4())


def _status_of(exc: BaseException) -> str:
    if isinstance(exc, UpstreamTimeout):
        return CallStatus.TIMEOUT
    if isinstance(exc, ContentBlocked):
        return CallStatus.BLOCKED
    return CallStatus.FAILED


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


class Gateway:
    # ------------------------------------------------------------ chat

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        role: str = "main",
        params: ChatParams | None = None,
        trace_id: str | None = None,
    ) -> ChatResult:
        if not messages:
            raise UpstreamBadRequest("messages 不能为空")
        trace_id = trace_id or _new_trace_id()
        params = params or ChatParams()
        started = time.monotonic()

        chain = router.chat_chain(role)  # type: ignore[arg-type]
        chain, forced_degraded = self._apply_budget(chain, trace_id)

        use_cache = settings.GW_CACHE_ENABLED and params.cacheable()
        cache_key = ""
        if use_cache:
            # 指纹要查库，async 上下文里必须切线程（ORM 是同步的）
            fingerprint = await asyncio.to_thread(cache.kb_fingerprint)
            cache_key = cache.chat_key(chain[0].model, messages, params, fingerprint)

        if use_cache:
            hit = cache.get(cache_key)
            if hit:
                meter.record(
                    trace_id=trace_id,
                    task=CallTask.CHAT,
                    provider=chain[0].slot,
                    model=hit["model"],
                    cached=True,
                    prompt_tokens=hit.get("prompt_tokens", 0),
                    completion_tokens=hit.get("completion_tokens", 0),
                    latency_ms=_elapsed_ms(started),
                    meta={"cache": "l1"},
                )
                await meter.maybe_flush()
                return ChatResult(
                    text=hit["text"],
                    model=hit["model"],
                    provider=chain[0].slot,
                    finish_reason=hit.get("finish_reason") or "stop",
                    prompt_tokens=hit.get("prompt_tokens", 0),
                    completion_tokens=hit.get("completion_tokens", 0),
                    degraded=False,
                    trace_id=trace_id,
                    cached=True,
                )

        errors: list[tuple[str, str]] = []
        tracker: dict[str, int] = {"attempt": 0}
        for idx, adapter in enumerate(chain):
            if not breaker.allow(adapter.slot):
                errors.append((adapter.slot, "CircuitOpen"))
                continue
            try:
                result = await retry.call_with_retry(
                    lambda _n, a=adapter: a.chat(messages, params), tracker
                )
            except Exception as exc:
                breaker.record_failure(adapter.slot)
                errors.append((adapter.slot, type(exc).__name__))
                meter.record(
                    trace_id=trace_id,
                    task=CallTask.CHAT,
                    provider=adapter.slot,
                    model=adapter.model,
                    status=_status_of(exc),
                    attempt=tracker["attempt"] or 1,
                    latency_ms=_elapsed_ms(started),
                    error=exc,
                )
                continue

            breaker.record_success(adapter.slot)
            degraded = idx > 0 or forced_degraded
            result = replace(
                result,
                provider=adapter.slot,
                degraded=degraded,
                trace_id=trace_id,
                cached=False,
            )
            meter.record(
                trace_id=trace_id,
                task=CallTask.CHAT,
                provider=adapter.slot,
                model=result.model,
                status=CallStatus.DEGRADED if degraded else CallStatus.OK,
                attempt=tracker["attempt"] or 1,
                prompt_tokens=result.prompt_tokens,
                completion_tokens=result.completion_tokens,
                latency_ms=_elapsed_ms(started),
            )
            if use_cache and result.text:
                cache.put(
                    cache_key,
                    {
                        "text": result.text,
                        "model": result.model,
                        "finish_reason": result.finish_reason,
                        "prompt_tokens": result.prompt_tokens,
                        "completion_tokens": result.completion_tokens,
                    },
                    settings.GW_CACHE_TTL_DEGRADED if degraded else settings.GW_CACHE_TTL_CHAT,
                )
            await meter.maybe_flush()
            return result

        await meter.maybe_flush()
        raise AllProvidersFailed(CallTask.CHAT, errors)

    async def chat_stream(
        self,
        messages: list[ChatMessage],
        *,
        role: str = "main",
        params: ChatParams | None = None,
        trace_id: str | None = None,
    ) -> AsyncIterator[ChatDelta]:
        if not messages:
            raise UpstreamBadRequest("messages 不能为空")
        trace_id = trace_id or _new_trace_id()
        params = params or ChatParams()
        started = time.monotonic()

        chain = router.chat_chain(role)  # type: ignore[arg-type]
        chain, forced_degraded = self._apply_budget(chain, trace_id)

        use_cache = settings.GW_CACHE_ENABLED and params.cacheable()
        cache_key = ""
        if use_cache:
            # 指纹要查库，async 上下文里必须切线程（ORM 是同步的）
            fingerprint = await asyncio.to_thread(cache.kb_fingerprint)
            cache_key = cache.chat_key(chain[0].model, messages, params, fingerprint)
        if use_cache:
            hit = cache.get(cache_key)
            if hit:
                text = hit.get("text") or ""
                for i in range(0, len(text), REPLAY_CHUNK):
                    yield ChatDelta(text=text[i : i + REPLAY_CHUNK])
                yield ChatDelta(text="", finish_reason=hit.get("finish_reason") or "stop")
                meter.record(
                    trace_id=trace_id,
                    task=CallTask.CHAT,
                    provider=chain[0].slot,
                    model=hit["model"],
                    cached=True,
                    stream=True,
                    prompt_tokens=hit.get("prompt_tokens", 0),
                    completion_tokens=hit.get("completion_tokens", 0),
                    latency_ms=_elapsed_ms(started),
                    meta={"cache": "l1"},
                )
                await meter.maybe_flush()
                return

        errors: list[tuple[str, str]] = []
        for idx, adapter in enumerate(chain):
            if not breaker.allow(adapter.slot):
                errors.append((adapter.slot, "CircuitOpen"))
                continue

            usage: dict = {}
            agen = adapter.stream(messages, params, usage)
            try:
                first = await agen.__anext__()
            except StopAsyncIteration:
                breaker.record_success(adapter.slot)
                await agen.aclose()
                return
            except Exception as exc:
                breaker.record_failure(adapter.slot)
                errors.append((adapter.slot, type(exc).__name__))
                await agen.aclose()
                meter.record(
                    trace_id=trace_id,
                    task=CallTask.CHAT,
                    provider=adapter.slot,
                    model=adapter.model,
                    status=_status_of(exc),
                    stream=True,
                    latency_ms=_elapsed_ms(started),
                    error=exc,
                )
                continue

            first_token_ms = _elapsed_ms(started) if first.text else None
            parts: list[str] = [first.text] if first.text else []
            yield first

            try:
                async for delta in agen:
                    if delta.text and first_token_ms is None:
                        first_token_ms = _elapsed_ms(started)
                    if delta.text:
                        parts.append(delta.text)
                    yield delta
            except Exception as exc:
                # 已输出内容，重试会重复一遍，只能断
                interrupted = StreamInterrupted(f"{adapter.slot} 输出中断: {exc}")
                meter.record(
                    trace_id=trace_id,
                    task=CallTask.CHAT,
                    provider=adapter.slot,
                    model=adapter.model,
                    status=CallStatus.FAILED,
                    stream=True,
                    latency_ms=_elapsed_ms(started),
                    first_token_ms=first_token_ms,
                    error=interrupted,
                    meta={"partial_chars": sum(len(p) for p in parts)},
                )
                await meter.maybe_flush()
                raise interrupted from exc

            breaker.record_success(adapter.slot)
            text = "".join(parts)
            model_name = usage.get("model") or adapter.model
            degraded = idx > 0 or forced_degraded
            meter.record(
                trace_id=trace_id,
                task=CallTask.CHAT,
                provider=adapter.slot,
                model=model_name,
                status=CallStatus.DEGRADED if degraded else CallStatus.OK,
                stream=True,
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
                latency_ms=_elapsed_ms(started),
                first_token_ms=first_token_ms,
            )
            if use_cache and text:
                cache.put(
                    cache_key,
                    {
                        "text": text,
                        "model": model_name,
                        "finish_reason": "stop",
                        "prompt_tokens": usage.get("prompt_tokens", 0),
                        "completion_tokens": usage.get("completion_tokens", 0),
                    },
                    settings.GW_CACHE_TTL_DEGRADED if degraded else settings.GW_CACHE_TTL_CHAT,
                )
            await meter.maybe_flush()
            return

        await meter.maybe_flush()
        raise AllProvidersFailed(CallTask.CHAT, errors)

    async def chat_json(
        self, messages: list[ChatMessage], *, schema: type[T], role: str = "aux"
    ) -> T:
        """结构化输出。校验失败回注一次，第二次仍失败直接抛错，不无限重试。"""
        from pydantic import TypeAdapter

        schema_text = json.dumps(schema.model_json_schema(), ensure_ascii=False)
        msgs = [
            *messages,
            ChatMessage(
                "user",
                "只输出符合下面 JSON Schema 的 JSON，不要解释、不要代码块：\n" + schema_text,
            ),
        ]
        params = ChatParams(temperature=0.0, json_mode=True)
        result = await self.chat(msgs, role=role, params=params)
        try:
            return TypeAdapter(schema).validate_json(result.text)
        except ValidationError as exc:
            repair = [
                *msgs,
                ChatMessage("assistant", result.text),
                ChatMessage("user", f"上面的输出不合规：{exc}。只返回修正后的 JSON。"),
            ]
            fixed = await self.chat(repair, role=role, params=params)
            try:
                return TypeAdapter(schema).validate_json(fixed.text)
            except ValidationError as exc2:
                raise UpstreamBadRequest(f"chat_json 两次都未返回合法结构：{exc2}") from exc2

    # ------------------------------------------------------------ embedding

    async def embed(
        self, texts: list[str], *, kind: Literal["doc", "query"] = "doc"
    ) -> list[list[float]]:
        if not texts:
            return []
        adapter = router.embed_adapter()  # 未配置直接抛 NotConfigured

        out: list[list[float] | None] = [None] * len(texts)
        misses: list[int] = []
        for i, text in enumerate(texts):
            hit = cache.get(cache.embed_key(adapter.model, kind, text))
            if hit is not None:
                out[i] = hit
            else:
                misses.append(i)

        if not misses:
            meter.record(
                trace_id=_new_trace_id(),
                task=CallTask.EMBEDDING,
                provider="embed",
                model=adapter.model,
                cached=True,
                meta={"batch": 0, "items": len(texts)},
            )
            await meter.maybe_flush()
            return [v or [] for v in out]

        if not breaker.allow("embed"):
            raise AllProvidersFailed(CallTask.EMBEDDING, [("embed", "CircuitOpen")])

        for start in range(0, len(misses), EMBED_BATCH):
            idxs = misses[start : start + EMBED_BATCH]
            batch = [texts[i] for i in idxs]
            tracker: dict[str, int] = {"attempt": 0}
            started = time.monotonic()
            try:
                result = await retry.call_with_retry(
                    lambda _n, b=batch: adapter.embed(b, kind), tracker
                )
            except GatewayError as exc:
                breaker.record_failure("embed")
                meter.record(
                    trace_id=_new_trace_id(),
                    task=CallTask.EMBEDDING,
                    provider="embed",
                    model=adapter.model,
                    status=_status_of(exc),
                    attempt=tracker["attempt"] or 1,
                    latency_ms=_elapsed_ms(started),
                    error=exc,
                    meta={"items": len(batch)},
                )
                await meter.maybe_flush()
                raise AllProvidersFailed(
                    CallTask.EMBEDDING, [("embed", type(exc).__name__)]
                ) from exc

            breaker.record_success("embed")
            for pos, vec in zip(idxs, result.vectors, strict=False):
                if len(vec) != settings.EMBEDDING_DIM:
                    raise DimensionMismatch(
                        f"期望 {settings.EMBEDDING_DIM} 维，{adapter.model} 返回 {len(vec)} 维"
                    )
                out[pos] = vec
                cache.put(
                    cache.embed_key(adapter.model, kind, texts[pos]),
                    vec,
                    settings.GW_CACHE_TTL_EMBED,
                )
            meter.record(
                trace_id=_new_trace_id(),
                task=CallTask.EMBEDDING,
                provider="embed",
                model=result.model,
                attempt=tracker["attempt"] or 1,
                prompt_tokens=result.prompt_tokens,
                latency_ms=_elapsed_ms(started),
                meta={"items": len(batch)},
            )

        await meter.maybe_flush()
        return [v or [] for v in out]

    # ------------------------------------------------------------ rerank

    async def rerank(
        self, query: str, docs: list[str], *, top_k: int = 10
    ) -> list[RankedDoc]:
        """未配置或失败都返回 []，由 P3 直接用融合分数截断——不重排是合法降级。"""
        if not query or not docs:
            return []
        adapter = router.rerank_adapter()
        if adapter is None:
            meter.record(
                trace_id=_new_trace_id(),
                task=CallTask.RERANK,
                provider="rerank",
                model="-",
                meta={"rerank": "not_configured"},
            )
            await meter.maybe_flush()
            return []

        key = cache.rerank_key(adapter.model, query, docs)
        hit = cache.get(key)
        if hit is not None:
            meter.record(
                trace_id=_new_trace_id(),
                task=CallTask.RERANK,
                provider="rerank",
                model=adapter.model,
                cached=True,
                meta={"items": len(docs)},
            )
            await meter.maybe_flush()
            return [RankedDoc(index=i, score=float(s)) for i, s in hit]

        if not breaker.allow("rerank"):
            return []

        tracker: dict[str, int] = {"attempt": 0}
        started = time.monotonic()
        try:
            ranked = await retry.call_with_retry(
                lambda _n: adapter.rerank(query, docs, top_k), tracker
            )
        except GatewayError as exc:
            breaker.record_failure("rerank")
            meter.record(
                trace_id=_new_trace_id(),
                task=CallTask.RERANK,
                provider="rerank",
                model=adapter.model,
                status=_status_of(exc),
                attempt=tracker["attempt"] or 1,
                latency_ms=_elapsed_ms(started),
                error=exc,
                meta={"rerank": "skipped"},
            )
            await meter.maybe_flush()
            return []

        breaker.record_success("rerank")
        cache.put(
            key,
            [(r.index, r.score) for r in ranked],
            settings.GW_CACHE_TTL_RERANK,
        )
        meter.record(
            trace_id=_new_trace_id(),
            task=CallTask.RERANK,
            provider="rerank",
            model=adapter.model,
            attempt=tracker["attempt"] or 1,
            latency_ms=_elapsed_ms(started),
            meta={"items": len(docs)},
        )
        await meter.maybe_flush()
        return ranked

    # ------------------------------------------------------------ 预算

    def _apply_budget(self, chain: list, trace_id: str) -> tuple[list, bool]:
        """超日预算后只留最便宜的一档；硬停则整条链放弃。"""
        if meter.budget_hard_stop():
            err = AllProvidersFailed(CallTask.CHAT, [("budget", "BudgetExceeded")])
            meter.record(
                trace_id=trace_id,
                task=CallTask.CHAT,
                provider="budget",
                model="-",
                status=CallStatus.FAILED,
                error=err,
            )
            raise err
        if meter.over_budget() and len(chain) > 1:
            return chain[-1:], True
        return chain, False


gateway = Gateway()
