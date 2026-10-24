"""M5–M9 串联：单轮作答入口。

顺序固定为 理解 → 检索 → 门槛 → 事项/槽位 → 生成 → 校验。每一步都能单独测，
所以这里只做编排，不放业务规则。P4 在这一层之上加会话与 fan-out，不改本文件。
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from django.conf import settings

from apps.gateway.base import (
    AllProvidersFailed,
    ContentBlocked,
    GatewayError,
    StreamInterrupted,
)
from apps.qa import generate, matters, prompts, retrieve, understand, verify
from apps.qa.types import (
    Answer,
    ChecklistItem,
    Citation,
    Conflict,
    Evidence,
    MatterMatch,
    QAEvent,
    RefusalReason,
    RetrievalResult,
    Slots,
    Understanding,
)

# 这几类问题属于"答案没有可核对的锚"，重写一次仍不过就不出答案
HARD_FAIL = {"no_citation", "bad_ref", "unverified_number"}


def _now_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _sources_text(evidence: list[Evidence], limit: int = 3) -> str:
    lines = []
    for e in evidence[:limit]:
        head = e.content.strip().replace("\n", " ")[:80]
        lines.append(f"{e.ref}. {e.label}\n   {head}…")
    return "\n".join(lines) if lines else "（无）"


@dataclass
class _GenerationContext:
    """通过门槛后、调用模型前需要准备的全部上下文。

    同步与流式只在生成策略上不同（是否修复重写），之前的门槛、事项、槽位、
    冲突和提示构造必须完全同口径，集中在这里避免两条路径慢慢漂移。
    """

    retrieval: RetrievalResult
    refusal: RefusalReason | None = None
    matter: MatterMatch | None = None
    slots: Slots = field(default_factory=Slots)
    conflicts: list[Conflict] = field(default_factory=list)
    notices: list[str] = field(default_factory=list)
    checklist: list[ChecklistItem] = field(default_factory=list)
    messages: list = field(default_factory=list)


def _citations(text: str, evidence: list[Evidence]) -> list[Citation]:
    by_ref = {e.ref: e for e in evidence}
    out = []
    for ref in verify.extract_refs(text):
        e = by_ref.get(ref)
        if e is None:
            continue
        out.append(
            Citation(
                ref=ref,
                chunk_id=e.chunk_id,
                document_id=e.document_id,
                title=e.title,
                section=e.section,
            )
        )
    return out


class QAService:
    async def answer(
        self,
        question: str,
        *,
        audience: str = "unknown",
        history: list[tuple[str, str]] | None = None,
        doc_types: list[str] | None = None,
        trace_id: str | None = None,
        understanding: Understanding | None = None,
    ) -> Answer:
        started = time.monotonic()
        trace_id = trace_id or str(uuid.uuid4())
        text = (question or "").strip()

        if not text:
            return self._plain(
                text, RefusalReason.EMPTY, prompts.EMPTY_QUESTION, trace_id, started
            )
        if len(text) > settings.QA_MAX_QUESTION_CHARS:
            return self._plain(
                text,
                RefusalReason.TOO_LONG,
                prompts.template(prompts.TOO_LONG, limit=settings.QA_MAX_QUESTION_CHARS),
                trace_id,
                started,
            )

        # P4 已经为路由算过一次意图，这里直接复用，避免一问两次 aux 调用
        u = understanding or await understand.understand(
            text, audience=audience, history=history
        )
        if u.intent.value == "smalltalk":
            return self._plain(text, None, prompts.SMALLTALK, trace_id, started, u=u, ok=True)
        if u.intent.value == "out_of_scope":
            return self._plain(
                text, RefusalReason.OUT_OF_SCOPE, prompts.OUT_OF_SCOPE, trace_id, started, u=u
            )

        prep = await self._prepare(text, u, doc_types)
        if prep.refusal is not None:
            return self._plain(
                text,
                prep.refusal,
                self._refusal_text(prep.refusal, text, prep.retrieval),
                trace_id,
                started,
                u=u,
                evidence=prep.retrieval.evidence[:2],
                meta={"recall": prep.retrieval.notes},
            )

        result, matter, slots = prep.retrieval, prep.matter, prep.slots
        conflicts, notices, checklist = prep.conflicts, prep.notices, prep.checklist
        messages = prep.messages

        try:
            gen = await generate.generate(messages, trace_id=trace_id)
        except (AllProvidersFailed, ContentBlocked) as exc:
            return self._plain(
                text,
                RefusalReason.UNGROUNDED,
                prompts.refusal_unavailable(type(exc).__name__, _sources_text(result.evidence)),
                trace_id,
                started,
                u=u,
                evidence=result.evidence,
                meta={"recall": result.notes},
            )

        report = verify.check(gen.text, result.evidence, conflicts)
        answer_text = gen.text
        repaired = False
        if not report.ok and settings.QA_REPAIR_MAX > 0:
            issues = [f"{i.detail}" for i in report.blocking]
            try:
                again = await generate.generate(
                    generate.build_repair_messages(messages, gen.text, issues),
                    trace_id=trace_id,
                )
            except (AllProvidersFailed, ContentBlocked):
                again = None
            if again is not None:
                second = verify.check(again.text, result.evidence, conflicts)
                if len(second.blocking) <= len(report.blocking):
                    report, answer_text, repaired = second, again.text, True

        hard = [i for i in report.blocking if i.code in HARD_FAIL]
        if hard:
            detail = "；".join(i.detail for i in hard)
            return Answer(
                question=text,
                intent=u.intent.value,
                answerable=False,
                text=prompts.refusal_unverified(detail, _sources_text(result.evidence)),
                refusal_reason=RefusalReason.UNGROUNDED.value,
                evidence=result.evidence,
                checklist=checklist,
                matter=matter,
                slots=slots,
                conflicts=conflicts,
                checks=report,
                understanding=u,
                notices=notices,
                degraded=gen.degraded,
                trace_id=trace_id,
                latency_ms=_now_ms(started),
                meta={"recall": result.notes, "model": gen.model, "repaired": repaired},
            )

        if not report.ok:
            notices.append(
                "自动核对未全部通过：" + "；".join(i.detail for i in report.blocking)
            )
        return Answer(
            question=text,
            intent=u.intent.value,
            answerable=True,
            text=answer_text,
            citations=_citations(answer_text, result.evidence),
            evidence=result.evidence,
            checklist=checklist,
            matter=matter,
            slots=slots,
            conflicts=conflicts,
            checks=report,
            understanding=u,
            notices=notices,
            degraded=gen.degraded,
            trace_id=trace_id,
            latency_ms=_now_ms(started),
            meta={"recall": result.notes, "model": gen.model, "repaired": repaired},
        )

    async def answer_stream(
        self,
        question: str,
        *,
        audience: str = "unknown",
        history: list[tuple[str, str]] | None = None,
        doc_types: list[str] | None = None,
        trace_id: str | None = None,
        understanding: Understanding | None = None,
    ) -> AsyncIterator[QAEvent]:
        """流式作答。已在吐字后无法撤回，所以流式路径不做修复重写（§8.3）。"""
        started = time.monotonic()
        trace_id = trace_id or str(uuid.uuid4())
        text = (question or "").strip()
        if not text:
            yield QAEvent("final", answer=self._plain(
                text, RefusalReason.EMPTY, prompts.EMPTY_QUESTION, trace_id, started
            ))
            return

        if understanding is None:
            yield QAEvent("stage", stage="understand")
            u = await understand.understand(text, audience=audience, history=history)
        else:
            # P4 已经为路由算过一次意图，这里直接复用，避免一问两次 aux 调用
            u = understanding
        if u.intent.value == "smalltalk":
            yield QAEvent("delta", text=prompts.SMALLTALK)
            yield QAEvent("final", answer=self._plain(
                text, None, prompts.SMALLTALK, trace_id, started, u=u, ok=True
            ))
            return
        if u.intent.value == "out_of_scope":
            yield QAEvent("delta", text=prompts.OUT_OF_SCOPE)
            yield QAEvent("final", answer=self._plain(
                text, RefusalReason.OUT_OF_SCOPE, prompts.OUT_OF_SCOPE, trace_id, started, u=u
            ))
            return

        yield QAEvent("stage", stage="retrieve")
        prep = await self._prepare(text, u, doc_types)
        if prep.refusal is not None:
            refusal = self._refusal_text(prep.refusal, text, prep.retrieval)
            yield QAEvent("delta", text=refusal)
            yield QAEvent("final", answer=self._plain(
                text, prep.refusal, refusal, trace_id, started, u=u,
                evidence=prep.retrieval.evidence[:2], meta={"recall": prep.retrieval.notes},
            ))
            return

        result, matter, slots = prep.retrieval, prep.matter, prep.slots
        conflicts, notices, checklist = prep.conflicts, prep.notices, prep.checklist
        messages = prep.messages

        parts: list[str] = []
        interrupted: str | None = None
        yield QAEvent("stage", stage="generate")
        try:
            async for piece in generate.generate_stream(messages, trace_id=trace_id):
                parts.append(piece)
                yield QAEvent("delta", text=piece)
        except StreamInterrupted as exc:
            interrupted = str(exc)
            yield QAEvent("error", detail=f"回答中断：{exc}")
        except GatewayError as exc:
            interrupted = type(exc).__name__
            yield QAEvent("error", detail=f"生成失败：{exc}")

        body = generate.normalize("".join(parts))
        report = verify.check(body, result.evidence, conflicts) if body else None
        if interrupted and not body:
            yield QAEvent("final", answer=self._plain(
                text, RefusalReason.UNGROUNDED,
                prompts.refusal_unavailable(interrupted, _sources_text(result.evidence)),
                trace_id, started, u=u, evidence=result.evidence,
            ))
            return
        if interrupted:
            notices.append("回答在该处中断，下面是已生成的部分内容，未核对完整。")

        hard = [i for i in (report.blocking if report else []) if i.code in HARD_FAIL]
        yield QAEvent("final", answer=Answer(
            question=text,
            intent=u.intent.value,
            answerable=not hard and bool(body),
            text=body,
            refusal_reason=RefusalReason.UNGROUNDED.value if hard else None,
            citations=_citations(body, result.evidence),
            evidence=result.evidence,
            checklist=checklist,
            matter=matter,
            slots=slots,
            conflicts=conflicts,
            checks=report,
            understanding=u,
            notices=notices,
            trace_id=trace_id,
            latency_ms=_now_ms(started),
            meta={"recall": result.notes, "stream": True, "repaired": False},
        ))

    # ------------------------------------------------------------ 内部

    async def _prepare(
        self,
        text: str,
        understanding: Understanding,
        doc_types: list[str] | None,
    ) -> _GenerationContext:
        """检索、门槛、事项与提示构造。生成策略由调用方决定，这里不碰模型。"""
        result = await retrieve.retrieve(understanding.rewritten, doc_types=doc_types)
        reason = verify.gate(result)
        if reason is not None:
            return _GenerationContext(retrieval=result, refusal=reason)

        matter = await asyncio.to_thread(
            matters.match_matter, understanding.rewritten, result.evidence
        )
        slots = matters.extract_slots(text, understanding)
        conflicts = verify.detect_conflicts(result.evidence)
        return _GenerationContext(
            retrieval=result,
            matter=matter,
            slots=slots,
            conflicts=conflicts,
            notices=matters.evaluate_rules(matter, slots, result.evidence),
            checklist=matters.build_checklist(matter, result.evidence),
            messages=generate.build_messages(
                text,
                understanding,
                result.evidence,
                matter=matter,
                slots=slots,
                conflicts=conflicts,
            ),
        )

    def _refusal_text(self, reason: RefusalReason, question: str, result) -> str:
        if reason is RefusalReason.NO_EVIDENCE:
            dept = result.evidence[0].dept if result.evidence else ""
            return prompts.refusal_no_evidence(question, dept)
        if result.reranked:
            basis = (
                f"最高重排分 {result.top_score:.2f}，"
                f"门槛 {settings.QA_MIN_RERANK_SCORE:.2f}"
            )
        else:
            basis = (
                f"最高相似度 {result.top_sim:.2f}（门槛 {settings.QA_MIN_VECTOR_SIM:.2f}），"
                f"命中词 {result.top_overlap} 个（门槛 {settings.QA_MIN_FTS_OVERLAP}）"
            )
        return prompts.refusal_low_confidence(basis)

    def _plain(
        self,
        question: str,
        reason: RefusalReason | None,
        text: str,
        trace_id: str,
        started: float,
        *,
        u: Understanding | None = None,
        evidence: list[Evidence] | None = None,
        meta: dict | None = None,
        ok: bool = False,
    ) -> Answer:
        return Answer(
            question=question,
            intent=u.intent.value if u else "",
            answerable=ok,
            text=text,
            refusal_reason=reason.value if reason else None,
            evidence=evidence or [],
            slots=Slots(),
            checklist=[],
            understanding=u,
            trace_id=trace_id,
            latency_ms=_now_ms(started),
            meta=meta or {},
        )


qa = QAService()
