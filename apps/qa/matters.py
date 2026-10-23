"""M7 事项与规则：事项匹配、槽位抽取、规则求值、清单与流程路径。

两条数据来源，优先级明确：
1. 事项库命中（matters + flows，P6 维护，`seed_matters` 提供基线）→ 结构化清单；
2. 事项库没命中 → 按召回块的 section_path 从小节标题里抽清单。
第 2 条是常态（P1 只建了表），所以抽取规则必须稳，不能依赖某一份语料的排版。
"""

from __future__ import annotations

import re

from apps.knowledge.models import Matter
from apps.knowledge.repositories import ReadRepository
from apps.qa import lexicon
from apps.qa.types import ChecklistItem, Evidence, MatterMatch, Slots, Understanding

MATERIAL_HINTS = ("所需材料", "申请材料", "提交材料", "材料")
STEP_HINTS = ("办理流程", "办理步骤", "申请流程", "流程", "步骤")
COND_HINTS = ("办理条件", "受理条件", "申请条件", "申报条件", "条件", "适用对象")

ITEM_PREFIX = re.compile(
    r"^\s*(?:[（(]?\d+[)）.、]|[①-⑩]|[（(][一二三四五六七八九十]+[)）]|[一二三四五六七八九十]+、)\s*"
)
STEP_SPLIT = re.compile(r"(?:^|\n)\s*第[一二三四五六七八九十]+步[:：]?\s*")
# 切分块会把相邻小节的正文并进同一行，条目尾部常拖着下一个标题，这里截断
HEADING_CUT = re.compile(r"\s*[一二三四五六七八九十]+、")
# 小节标题可能出现在块中间（标题与相邻正文被并进同一块），按出现位置再切一次
INLINE_HEADING = re.compile(r"([一二三四五六七八九十]+、[^\s。；，]{2,12})")
# 编号也可能被并进同一行："…一份。2. 一寸免冠照片一张。"
INLINE_NUMBER = re.compile(r"(?<=[。；;])\s*(?=\d{1,2}[.、)）])")
# 语料里跟在流程后面的统一模板句，不是条目内容
BOILERPLATE = re.compile(r"办理过程中可通过|均可通过网上办事大厅")
MAX_ITEMS = 10


def _clean(text: str) -> str:
    for pattern in (HEADING_CUT, BOILERPLATE):
        cut = pattern.search(text)
        if cut:
            text = text[: cut.start()]
    return re.sub(r"\s+", " ", text).strip(" 。；;，,、：:")


def _strip_heading(text: str, heading: str) -> str:
    """块内容常把标题并进正文（P1 切分口径），先去掉这一行。"""
    first, sep, rest = text.partition("\n")
    head = first.strip()
    if not sep:
        return text
    if heading and (head == heading or heading in head) and not ITEM_PREFIX.match(head):
        return rest
    if re.match(r"^[一二三四五六七八九十]+、", head):
        return rest
    return text


def split_sections(text: str) -> list[tuple[str, str]]:
    """把一块正文按内联小节标题切开，返回 [(小节名, 正文)]。

    切分阶段标题只记 section_path（块首的那个），块中间的标题会跟着正文一起进来，
    材料/流程小节因此经常整段落在"一、事项概述"这个块里。清单要准，必须再切一刀。
    """
    marks = list(INLINE_HEADING.finditer(text))
    if not marks:
        return [("", text)]
    out: list[tuple[str, str]] = []
    if marks[0].start() > 0:
        out.append(("", text[: marks[0].start()]))
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        out.append((m.group(1).strip(), text[m.end() : end]))
    return out


def _numbered(body: str) -> list[str]:
    body = INLINE_NUMBER.sub("\n", body)
    out: list[str] = []
    for line in body.splitlines():
        if not ITEM_PREFIX.match(line.strip()):
            continue
        value = _clean(ITEM_PREFIX.sub("", line.strip()))
        if len(value) >= 4:
            out.append(value[:160])
    return out


def items_from(text: str, heading: str = "", ordered: bool = False) -> list[str]:
    """把一小节正文拆成条目：优先"第一步/第二步"，其次编号项，最后按分号。

    ordered=True 用于流程与材料小节：没有序号的句子一律丢弃——切分块会把上一小节
    的尾巴并进同一块，靠序号过滤比靠位置猜更稳，也顺手挡掉了散文式说明。
    """
    body = _strip_heading(text, heading)
    first = STEP_SPLIT.search(body)
    if first:                       # 第一个"第N步"之前是上一小节的尾巴，丢掉
        body = body[first.start() :]
    steps = [s for s in STEP_SPLIT.split(body) if _clean(s)]
    if len(steps) >= 2:
        return [_clean(s)[:160] for s in steps if _clean(s)][:MAX_ITEMS]

    numbered = _numbered(body)
    if ordered or numbered:
        return numbered[:MAX_ITEMS]

    items: list[str] = []
    for line in body.splitlines():
        for piece in re.split(r"[；;]", line):
            value = _clean(piece)
            if len(value) >= 6 and not value.endswith("："):
                items.append(value[:160])
    return items[:MAX_ITEMS]


def kind_of(section: str) -> str | None:
    """小节名 → 清单类型。顺序不能换：材料优先于条件，避免"材料要求"被判成条件。

    注意事项/说明不进清单：那是散文，按句切出来全是碎片，清单只需要可勾选的条目。
    """
    if any(h in section for h in MATERIAL_HINTS):
        return "material"
    if any(h in section for h in STEP_HINTS):
        return "step"
    if any(h in section for h in COND_HINTS):
        return "condition"
    return None


def extract_slots(question: str, understanding: Understanding | None = None) -> Slots:
    """槽位以规则为主：身份与渠道是硬约束，不能交给模型自由发挥。"""
    audience = lexicon.audience_of(question)
    if audience == "unknown" and understanding and understanding.audience != "unknown":
        audience = understanding.audience
    urgent = ("加急", "着急", "尽快", "马上", "急用")
    urgency = "urgent" if any(w in question for w in urgent) else "normal"
    return Slots(
        audience=audience,
        channel=lexicon.channel_of(question),
        urgency=urgency,
        signals={"demand": lexicon.keyword(question, 4)},
    )


def match_matter(
    question: str, evidence: list[Evidence], repo: ReadRepository | None = None
) -> MatterMatch | None:
    """先查事项库（名称包含/字面重合），再按召回文档标题派生。"""
    repo = repo or ReadRepository()
    best: tuple[Matter, float] | None = None
    for matter in repo.matters():
        name = matter.name or ""
        if not name:
            continue
        if name in question:
            score = 1.0
        else:
            chars = set(name)
            score = len(chars & set(question)) / len(chars)
            if score < 0.8:
                continue
        if best is None or score > best[1]:
            best = (matter, score)

    if best is not None:
        row, score = best
        flows = list(repo.flows_of(row))
        materials = [str(m) for f in flows for m in (f.materials or [])]
        return MatterMatch(
            code=row.code,
            name=row.name,
            dept=row.dept,
            location=row.location,
            contact=row.contact,
            audience=row.audience,
            summary=row.summary,
            source="table",
            score=score,
            steps=[
                f"{f.title}：{f.description}" if f.description else f.title for f in flows
            ],
            materials=materials,
        )

    for e in evidence:
        if e.doc_type == "guide":
            return MatterMatch(
                code=f"doc-{e.document_id}",
                name=e.title,
                dept=e.dept,
                source="derived",
                score=0.5,
            )
    if evidence:
        top = evidence[0]
        return MatterMatch(
            code=f"doc-{top.document_id}",
            name=top.title,
            dept=top.dept,
            source="derived",
            score=0.3,
        )
    return None


def build_checklist(
    matter: MatterMatch | None, evidence: list[Evidence]
) -> list[ChecklistItem]:
    """清单：事项库有结构化数据就用它，否则从小节标题抽。同文去重、保序。"""
    items: list[ChecklistItem] = []
    seen: set[str] = set()

    def _push(kind: str, text: str, ref: int | None) -> None:
        key = text.replace(" ", "")
        if not key or key in seen or len(items) >= 3 * MAX_ITEMS:
            return
        seen.add(key)
        items.append(ChecklistItem(kind=kind, text=text, ref=ref, ordinal=len(items) + 1))

    if matter is not None and matter.source == "table":
        for text in matter.materials:
            _push("material", text, None)
        for text in matter.steps:
            _push("step", text, None)

    related = evidence
    if matter is not None:
        same = [e for e in evidence if e.title == matter.name]
        related = same or evidence[:3]
    for e in related:
        for heading, body in split_sections(e.content):
            kind = kind_of(heading or e.section)
            if kind is None:
                continue
            for text in items_from(body, heading or e.section, ordered=True):
                _push(kind, text, e.ref)
    return items


def evaluate_rules(
    matter: MatterMatch | None, slots: Slots, evidence: list[Evidence]
) -> list[str]:
    """规则求值只产出"提示"，不改答案、不拦截。拦截一律交给 M9 的可答性判定。"""
    notices: list[str] = []

    if matter and matter.audience and slots.audience not in ("unknown", matter.audience):
        label = {"undergrad": "本科生", "grad": "研究生", "staff": "教职工", "alumni": "校友"}
        notices.append(
            f"该事项面向{label.get(matter.audience, matter.audience)}，"
            f"你的身份是{label.get(slots.audience, slots.audience)}，请先确认是否受理。"
        )

    if slots.urgency == "urgent":
        notices.append("知识库未收录加急办理规则，下面的时限均为常规办理口径。")

    effective = sorted({e.effective_from for e in evidence if e.effective_from})
    if len(effective) == 1:
        notices.append(f"依据自 {effective[0]} 起施行的版本，如有新版以新版为准。")
    return notices
