"""M5–M9 之间交接的数据类型。

约定：模块之间只通过这些 dataclass 传递，不互相 import 内部结构；
引用编号 ref 在 M6 出结果时定死，后续各环节只读不改。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Intent(str, Enum):
    """意图。除 matter/policy/faq 外都不检索、不生成，直接确定性回话。"""

    MATTER = "matter"          # 办事事项：怎么办、要什么材料
    POLICY = "policy"          # 制度口径：允不允许、标准是多少
    FAQ = "faq"                # 常见问题：时间、地点、能不能
    SMALLTALK = "smalltalk"    # 打招呼、问能力边界
    OUT_OF_SCOPE = "out_of_scope"  # 与校园业务无关


class RefusalReason(str, Enum):
    """拒答口径。评测里逐类统计，不混成一个"未回答"。"""

    EMPTY = "empty_question"
    TOO_LONG = "too_long"
    OUT_OF_SCOPE = "out_of_scope"
    NO_EVIDENCE = "no_evidence"
    LOW_CONFIDENCE = "low_confidence"
    UNGROUNDED = "ungrounded"


@dataclass(frozen=True)
class Understanding:
    """M5 输出。rules 来源表示模型不可用时的兜底，评测里单独看命中率。"""

    intent: Intent
    original: str
    rewritten: str
    audience: str = "unknown"
    confidence: float = 0.0
    keyword: str = ""
    sub_questions: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    source: str = "llm"


@dataclass(frozen=True)
class Evidence:
    """一块证据。score 是最终用于排序的分（重排分或归一化融合分）。"""

    ref: int
    chunk_id: int
    document_id: int
    title: str
    doc_type: str
    dept: str
    section: str
    page: int
    content: str
    score: float                    # 排序分：重排分，或归一化融合分
    fusion: float                   # RRF 归一化分，只看排名
    similarity: float = 0.0         # 余弦相似度，绝对量，用于门槛
    overlap: int = 0                # 命中的查询词数，绝对量，用于门槛
    source: str = "both"            # vector / fts / both
    rank_vector: int | None = None
    rank_fts: int | None = None
    effective_from: str = ""         # 依据的施行日期，ISO 字符串，空表示文档未标

    @property
    def label(self) -> str:
        """给提示用的来源标签，不带内部 id（模型会照抄 id 编引用）。"""
        parts = [self.title]
        if self.section:
            parts.append(self.section)
        if self.page > 1:
            parts.append(f"第{self.page}页")
        return " · ".join(parts)


@dataclass
class RetrievalResult:
    query: str
    evidence: list[Evidence] = field(default_factory=list)
    top_score: float = 0.0
    top_sim: float = 0.0
    top_overlap: int = 0
    reranked: bool = False
    vector_hits: int = 0
    fts_hits: int = 0
    answerable: bool = False
    reason: str | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def titles(self) -> list[str]:
        out: list[str] = []
        for e in self.evidence:
            if e.title not in out:
                out.append(e.title)
        return out


@dataclass
class Slots:
    """M7 槽位。目前只抽四类，其余留给 P4 在多轮里补。"""

    audience: str = "unknown"        # undergrad / grad / staff / alumni / unknown
    channel: str = "unknown"         # online / offline / both / unknown
    urgency: str = "normal"
    location: str = ""
    signals: dict = field(default_factory=dict)


@dataclass(frozen=True)
class MatterMatch:
    """事项匹配结果。source=derived 表示知识库里还没有该事项行，按语料标题派生。"""

    code: str
    name: str
    dept: str = ""
    location: str = ""
    contact: str = ""
    audience: str = ""
    summary: str = ""
    source: str = "table"            # table / derived
    score: float = 0.0
    steps: list[str] = field(default_factory=list)
    materials: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ChecklistItem:
    kind: str                        # material / step / condition / notice
    text: str
    ref: int | None = None
    ordinal: int = 0


@dataclass(frozen=True)
class Conflict:
    """同一字段在不同证据里给了不同值。检测到就必须并列说明，不许取一个。"""

    field: str
    values: list[str]
    refs: list[int]


@dataclass(frozen=True)
class Citation:
    ref: int
    chunk_id: int
    document_id: int
    title: str
    section: str


@dataclass(frozen=True)
class Issue:
    code: str
    detail: str
    blocking: bool = False


@dataclass
class VerifyReport:
    """M9 输出。ok=False 且存在 blocking 时走修复重写，二次仍不过则标未核实。"""

    ok: bool = True
    citation_coverage: float = 0.0
    refs: list[int] = field(default_factory=list)
    bad_refs: list[int] = field(default_factory=list)
    unverified_numbers: list[str] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    repaired: bool = False

    @property
    def blocking(self) -> bool:
        return [i for i in self.issues if i.blocking]


@dataclass
class Answer:
    question: str
    intent: str
    answerable: bool
    text: str
    refusal_reason: str | None = None
    citations: list[Citation] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    checklist: list[ChecklistItem] = field(default_factory=list)
    matter: MatterMatch | None = None
    slots: Slots = field(default_factory=Slots)
    conflicts: list[Conflict] = field(default_factory=list)
    checks: VerifyReport | None = None
    understanding: Understanding | None = None
    notices: list[str] = field(default_factory=list)
    degraded: bool = False
    trace_id: str = ""
    latency_ms: int = 0
    meta: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        """给 /api/qa/ask 与离线评测用。字段名与前端约定一致，不暴露内部对象。"""
        return {
            "question": self.question,
            "intent": self.intent,
            "answerable": self.answerable,
            "text": self.text,
            "refusal_reason": self.refusal_reason,
            "notices": self.notices,
            "degraded": self.degraded,
            "latency_ms": self.latency_ms,
            "trace_id": self.trace_id,
            "matter": None
            if self.matter is None
            else {
                "code": self.matter.code,
                "name": self.matter.name,
                "dept": self.matter.dept,
                "location": self.matter.location,
                "contact": self.matter.contact,
                "source": self.matter.source,
                "score": round(self.matter.score, 3),
            },
            "slots": {
                "audience": self.slots.audience,
                "channel": self.slots.channel,
                "urgency": self.slots.urgency,
            },
            "understanding": None
            if self.understanding is None
            else {
                "rewritten": self.understanding.rewritten,
                "keyword": self.understanding.keyword,
                "confidence": round(self.understanding.confidence, 3),
                "source": self.understanding.source,
                "sub_questions": self.understanding.sub_questions,
                "missing": self.understanding.missing,
            },
            "citations": [
                {
                    "ref": c.ref,
                    "chunk_id": c.chunk_id,
                    "document_id": c.document_id,
                    "title": c.title,
                    "section": c.section,
                }
                for c in self.citations
            ],
            "evidence": [
                {
                    "ref": e.ref,
                    "chunk_id": e.chunk_id,
                    "title": e.title,
                    "section": e.section,
                    "page": e.page,
                    "doc_type": e.doc_type,
                    "score": round(e.score, 4),
                    # 双栏对照要显示原文；块本身不超过 CHUNK_SIZE(500)，这里再压一道
                    "content": e.content[:600],
                    "sim": round(e.similarity, 4),
                    "overlap": e.overlap,
                    "source": e.source,
                }
                for e in self.evidence
            ],
            "checklist": [
                {"kind": i.kind, "text": i.text, "ref": i.ref, "ordinal": i.ordinal}
                for i in self.checklist
            ],
            "conflicts": [
                {"field": c.field, "values": c.values, "refs": c.refs} for c in self.conflicts
            ],
            "checks": None
            if self.checks is None
            else {
                "ok": self.checks.ok,
                "citation_coverage": round(self.checks.citation_coverage, 3),
                "refs": self.checks.refs,
                "bad_refs": self.checks.bad_refs,
                "unverified_numbers": self.checks.unverified_numbers,
                "repaired": self.checks.repaired,
                "issues": [
                    {"code": i.code, "detail": i.detail, "blocking": i.blocking}
                    for i in self.checks.issues
                ],
            },
            "meta": self.meta,
        }


@dataclass
class QAEvent:
    """流式事件。P4 负责转成 SSE 帧，P3 只给语义。"""

    type: str                        # stage / delta / final / error
    stage: str = ""
    text: str = ""
    answer: Answer | None = None
    detail: str = ""
