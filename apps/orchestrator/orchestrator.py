"""M4 编排器：一轮 = 载入会话 → 理解 → 路由 → 执行（单段或 fan-out）→ 装配 → 落库。

两条路径的取舍写在这里，免得后面被人"优化"掉：

- `turn()` 非流式：修复重写可用（走 P3 的 `answer`），用于评测与 P7 回归。
- `stream()` 单段走 P3 的真流式；**多子问题并行时只整段吐出**——并行结果无法边算边拼，
  硬做只能先缓冲全部再切片，那就是假流式，首字延迟反而更差。
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid

from django.utils import timezone

from apps.orchestrator import assembler, capabilities, events, router, session
from apps.orchestrator.capabilities import TurnContext
from apps.orchestrator.models import Conversation, Message
from apps.orchestrator.router import FANOUT, SINGLE
from apps.qa import understand

logger = logging.getLogger(__name__)


def _now_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


class Orchestrator:
    # ------------------------------------------------------------ 非流式
    async def turn(
        self,
        question: str,
        *,
        user_key: str = "demo",
        conversation_id: str | None = None,
        audience: str = "unknown",
        doc_types: list[str] | None = None,
        trace_id: str | None = None,
    ) -> assembler.TurnResult:
        started = time.monotonic()
        trace_id = trace_id or str(uuid.uuid4())
        state = await asyncio.to_thread(
            session.load_or_create, conversation_id, user_key, audience
        )
        state.turn += 1
        raw = (question or "").strip()

        if not raw:
            result = self._empty_result(state, raw, trace_id, started)
            await asyncio.to_thread(self._persist, state, raw, result)
            return result

        enriched, patched = router.enrich(raw, state)
        understanding = await understand.understand(
            enriched, audience=state.audience, history=state.history_pairs()
        )
        plan = router.plan_for(understanding, state)
        answers = await self._execute(plan, understanding, state, doc_types, trace_id)

        result = self._assemble(
            state, raw, answers, plan, patched, trace_id, started
        )
        await asyncio.to_thread(self._persist, state, raw, result)
        return result

    def _empty_result(
        self,
        state: session.SessionState,
        raw: str,
        trace_id: str,
        started: float,
    ) -> assembler.TurnResult:
        """空问题也返回一份完整 TurnResult，落库与前端都按正常轮次处理。"""
        ctx = TurnContext(question=raw, audience=state.audience, trace_id=trace_id)
        return assembler.assemble(
            conversation_id=state.conversation_id,
            turn=state.turn,
            question=raw,
            answers=[capabilities.empty_answer(ctx)],
            mode=SINGLE,
            trace_id=trace_id,
            latency_ms=_now_ms(started),
        )

    def _assemble(
        self,
        state: session.SessionState,
        raw: str,
        answers: list,
        plan: router.Plan,
        patched: bool,
        trace_id: str,
        started: float,
        *,
        streamed: bool = False,
    ) -> assembler.TurnResult:
        """统一装配元信息，避免同步/流式/fan-out 三处 meta 各写一份。"""
        meta = {
            "plan": plan.reason,
            "enriched": patched,
            "matter_name": assembler.matter_name_of(answers),
            "segments": len(plan.segments),
        }
        if streamed:
            meta["stream"] = True
        return assembler.assemble(
            conversation_id=state.conversation_id,
            turn=state.turn,
            question=raw,
            answers=answers,
            mode=plan.mode,
            trace_id=trace_id,
            latency_ms=_now_ms(started),
            meta=meta,
        )

    async def _execute(
        self,
        plan: router.Plan,
        understanding,
        state: session.SessionState,
        doc_types: list[str] | None,
        trace_id: str,
    ) -> list:
        history = state.history_pairs()
        if plan.mode == FANOUT:
            # 多段共用同一个 trace_id：ai_calls.trace_id 是 UUID 字段，
            # 拼 ":0" 之类的后缀会让台账落库直接失败；一次请求本就该一个 trace
            ctxs = [
                TurnContext(
                    question=seg,
                    audience=state.audience,
                    history=history,
                    doc_types=doc_types,
                    trace_id=trace_id,
                )
                for seg in plan.segments
            ]
            # 子问题之间没有依赖，并行；单段超时由 capabilities 负责，不互相拖死
            return list(await asyncio.gather(*(capabilities.answer(c) for c in ctxs)))

        ctx = TurnContext(
            question=plan.segments[0],
            audience=state.audience,
            history=history,
            doc_types=doc_types,
            trace_id=trace_id,
        )
        return [await capabilities.answer(ctx, understanding=understanding)]

    # ------------------------------------------------------------ 流式
    async def stream(
        self,
        question: str,
        *,
        user_key: str = "demo",
        conversation_id: str | None = None,
        audience: str = "unknown",
        doc_types: list[str] | None = None,
        trace_id: str | None = None,
    ):
        started = time.monotonic()
        trace_id = trace_id or str(uuid.uuid4())
        state = await asyncio.to_thread(
            session.load_or_create, conversation_id, user_key, audience
        )
        state.turn += 1
        raw = (question or "").strip()
        yield events.session_frame(state.conversation_id, state.turn)

        try:
            if not raw:
                result = self._empty_result(state, raw, trace_id, started)
                yield events.sse(events.DELTA, {"text": result.text})
                yield events.sse(events.ANSWER, result.as_dict())
                await asyncio.to_thread(self._persist, state, raw, result)
            else:
                yield events.stage_frame("understand")
                enriched, patched = router.enrich(raw, state)
                understanding = await understand.understand(
                    enriched, audience=state.audience, history=state.history_pairs()
                )
                plan = router.plan_for(understanding, state)
                yield events.stage_frame(
                    "route", mode=plan.mode, segments=len(plan.segments)
                )

                if plan.mode == FANOUT:
                    yield events.stage_frame("fanout", segments=len(plan.segments))
                    answers = await self._execute(
                        plan, understanding, state, doc_types, trace_id
                    )
                    result = self._assemble(
                        state, raw, answers, plan, patched, trace_id, started
                    )
                    yield events.sse(events.DELTA, {"text": result.text})
                    yield events.sse(events.ANSWER, result.as_dict())
                    if result.failed_segments:
                        text = (
                            f"有 {result.failed_segments} 个子问题没有答出来，"
                            "其余部分已保留。"
                        )
                        yield events.sse(events.NOTICE, {"level": "warn", "text": text})
                    await asyncio.to_thread(self._persist, state, raw, result)
                else:
                    ctx = TurnContext(
                        question=plan.segments[0],
                        audience=state.audience,
                        history=state.history_pairs(),
                        doc_types=doc_types,
                        trace_id=trace_id,
                    )
                    final = None
                    async for event in capabilities.stream(ctx, understanding=understanding):
                        if event.type == "stage":
                            yield events.stage_frame(event.stage)
                        elif event.type == "delta":
                            yield events.sse(events.DELTA, {"text": event.text})
                        elif event.type == "error":
                            yield events.sse(events.ERROR, {"message": event.detail})
                        elif event.type == "final" and event.answer is not None:
                            final = event.answer
                    if final is None:              # 理论上不会：stream() 一定以 final 收尾
                        final = capabilities.failed_answer(ctx, "no_final")
                    result = self._assemble(
                        state,
                        raw,
                        [final],
                        plan,
                        patched,
                        trace_id,
                        started,
                        streamed=True,
                    )
                    yield events.sse(events.ANSWER, result.as_dict())
                    await asyncio.to_thread(self._persist, state, raw, result)
        except Exception as exc:                   # 兜底：出错也要给前端一个收尾
            logger.exception("orchestrator 流式失败 trace=%s", trace_id)
            yield events.sse(events.ERROR, {"message": f"{type(exc).__name__}: {exc}"})

        yield events.sse(
            events.DONE,
            {
                "conversation_id": state.conversation_id,
                "turn": state.turn,
                "latency_ms": _now_ms(started),
                "trace_id": trace_id,
            },
        )

    # ------------------------------------------------------------ 落库
    def _persist(self, state: session.SessionState, question: str, result) -> None:
        """同步写库，由调用方切线程。同一 (会话, 轮次, 角色) 复写而不是追加。"""
        conv = Conversation.objects.filter(pk=state.conversation_id).first()
        if conv is None:
            conv = Conversation.objects.create(
                id=state.conversation_id,
                user_key=state.user_key,
                audience=state.audience,
                last_active_at=timezone.now(),
            )
        Message.objects.update_or_create(
            conversation=conv,
            turn=result.turn,
            role=Message.Role.USER,
            defaults={"content": question, "trace_id": result.trace_id},
        )
        Message.objects.update_or_create(
            conversation=conv,
            turn=result.turn,
            role=Message.Role.ASSISTANT,
            defaults={
                "content": result.text,
                "intent": result.intent,
                "answerable": result.answerable,
                "refusal_reason": result.segments[0].refusal_reason if result.segments else "",
                "trace_id": result.trace_id,
                "latency_ms": result.latency_ms,
                "payload": result.as_dict(),
            },
        )
        conv.turn_count = max(conv.turn_count, result.turn)
        conv.last_active_at = timezone.now()
        if not conv.title and question:
            conv.title = question[:60]
        conv.audience = state.audience or conv.audience
        conv.save(update_fields=["turn_count", "last_active_at", "title", "audience"])

        session.append_turn(
            state,
            question,
            result.text,
            matter=result.meta.get("matter_name", ""),
            intent=result.intent,
        )
        session.save(state)


orc = Orchestrator()
