"""结果装配：把一段或多段 Answer 装成一次 turn 的对外结果。

多段不是把文本拼起来就完事：引用、清单、提示都要合并去重，且保留"来自第几段"，
否则 P5 的双栏对照点不出这句引用属于哪个子问题。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from apps.qa.types import Answer

MARKS = "①②③④⑤⑥⑦⑧⑨"


@dataclass
class Segment:
    index: int
    question: str
    intent: str
    answerable: bool
    text: str
    citations: list[dict] = field(default_factory=list)
    evidence: list[dict] = field(default_factory=list)
    checklist: list[dict] = field(default_factory=list)
    notices: list[str] = field(default_factory=list)
    refusal_reason: str = ""
    failed: bool = False


@dataclass
class TurnResult:
    conversation_id: str
    turn: int
    question: str
    text: str
    mode: str
    intent: str
    answerable: bool
    trace_id: str
    latency_ms: int
    degraded: bool = False
    failed_segments: int = 0
    segments: list[Segment] = field(default_factory=list)
    citations: list[dict] = field(default_factory=list)
    checklist: list[dict] = field(default_factory=list)
    notices: list[str] = field(default_factory=list)
    meta: dict = field(default_factory=dict)

    @property
    def refusal_reason(self) -> str:
        """首段拒答原因，供前端用统一文案说明"为什么没答"。"""
        return self.segments[0].refusal_reason if self.segments else ""

    def as_dict(self) -> dict:
        return {
            "conversation_id": self.conversation_id,
            "turn": self.turn,
            "question": self.question,
            "text": self.text,
            "mode": self.mode,
            "intent": self.intent,
            "answerable": self.answerable,
            "refusal_reason": self.refusal_reason,
            "degraded": self.degraded,
            "failed_segments": self.failed_segments,
            "trace_id": self.trace_id,
            "latency_ms": self.latency_ms,
            "notices": self.notices,
            "matter_name": self.meta.get("matter_name", ""),
            "meta": self.meta,
            "segments": [
                {
                    "index": s.index,
                    "question": s.question,
                    "intent": s.intent,
                    "answerable": s.answerable,
                    "text": s.text,
                    "failed": s.failed,
                    "refusal_reason": s.refusal_reason,
                    "citations": s.citations,
                    "evidence": s.evidence,
                    "checklist": s.checklist,
                    "notices": s.notices,
                }
                for s in self.segments
            ],
            "citations": self.citations,
            "checklist": self.checklist,
        }


def _blocking_details(checks: dict | None) -> list[str]:
    """校验里的阻塞项也当提示带出来：用户该知道"这句没核实"。"""
    if not checks:
        return []
    return [i["detail"] for i in checks.get("issues", []) if i.get("blocking")]


def _segment_of(index: int, answer: Answer) -> Segment:
    data = answer.as_dict()
    return Segment(
        index=index,
        question=data["question"] or answer.question,
        intent=data["intent"],
        answerable=data["answerable"],
        text=data["text"],
        citations=data["citations"],
        evidence=data["evidence"],
        checklist=data["checklist"],
        refusal_reason=data["refusal_reason"] or "",
        notices=data["notices"] + _blocking_details(data["checks"]),
        failed=bool(data["meta"].get("failed")),
    )


def assemble(
    *,
    conversation_id: str,
    turn: int,
    question: str,
    answers: list[Answer],
    mode: str,
    trace_id: str,
    latency_ms: int,
    meta: dict | None = None,
) -> TurnResult:
    segments = [_segment_of(i, a) for i, a in enumerate(answers)]
    failed = sum(1 for s in segments if s.failed)

    if len(segments) == 1:
        text = segments[0].text
    else:
        text = "\n\n".join(f"{MARKS[s.index]} {s.text}" for s in segments)

    citations: list[dict] = []
    by_chunk: dict[int, dict] = {}
    for seg in segments:
        for cit in seg.citations:
            existing = by_chunk.get(cit["chunk_id"])
            if existing is None:
                entry = {**cit, "segments": [seg.index]}
                by_chunk[cit["chunk_id"]] = entry
                citations.append(entry)
            elif seg.index not in existing["segments"]:
                existing["segments"].append(seg.index)

    checklist: list[dict] = []
    seen: set[str] = set()
    for seg in segments:
        for item in seg.checklist:
            key = (item["text"] or "").replace(" ", "")
            if not key or key in seen:
                continue
            seen.add(key)
            checklist.append({**item, "ordinal": len(checklist) + 1, "segment": seg.index})

    notices = [f"第{seg.index + 1}段：{n}" if len(segments) > 1 else n
               for seg in segments for n in seg.notices]

    return TurnResult(
        conversation_id=conversation_id,
        turn=turn,
        question=question,
        text=text,
        mode=mode,
        intent=segments[0].intent if segments else "",
        answerable=any(s.answerable for s in segments),
        trace_id=trace_id,
        latency_ms=latency_ms,
        degraded=any(a.degraded for a in answers),
        failed_segments=failed,
        segments=segments,
        citations=citations,
        checklist=checklist,
        notices=notices,
        meta=meta or {},
    )


def matter_name_of(answers: list[Answer]) -> str:
    for answer in answers:
        if answer.matter is not None and answer.matter.name:
            return answer.matter.name
    return ""
