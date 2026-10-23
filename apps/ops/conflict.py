"""审核期的口径冲突检测。

审的是"新版本与在版说法是否打架"，所以只比**同事项**的数值：
时限（X 个工作日）与费用（X 元/份）。跨事项比必然误报——学生证 3 个工作日、
成绩单 5 个工作日本来就不同。

与 P3 的 `verify.detect_conflicts` 是同一套口径但两种用途：那边判"回答里有没有
并列说明"，这边判"发布前要不要提醒编辑"。故意不共用代码：一个在 L4 服务线上问答，
一个在 L1 服务审核流程，耦合起来两边都不好改。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from apps.knowledge.models import Chunk, Document, PublishStatus

# 语料里费用两种写法混用："每份 20 元" 与 "20 元/份"，只认一种会漏检
COST_A = re.compile(r"(\d+(?:\.\d+)?)\s*元\s*(?:/|每)?\s*(份|次|人|张|页)")
COST_B = re.compile(r"每\s*(份|次|人|张|页)\s*(\d+(?:\.\d+)?)\s*元")
HOURS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:个)?工作日")
TITLE_OVERLAP = 0.6


@dataclass(frozen=True)
class Conflict:
    field: str
    draft_value: str
    published_value: str
    published_doc: str
    published_doc_id: int

    def as_dict(self) -> dict:
        return {
            "field": self.field,
            "draft": self.draft_value,
            "published": self.published_value,
            "published_doc": self.published_doc,
            "published_doc_id": self.published_doc_id,
        }


def _similar(a: str, b: str) -> bool:
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return False
    return len(sa & sb) / min(len(sa), len(sb)) >= TITLE_OVERLAP


def _facts(text: str) -> dict[str, set[str]]:
    facts: dict[str, set[str]] = {"费用": set(), "时限": set()}
    for m in COST_A.finditer(text):
        facts["费用"].add(f"{_num(m.group(1))}元/{m.group(2)}")
    for m in COST_B.finditer(text):
        facts["费用"].add(f"{_num(m.group(2))}元/{m.group(1)}")
    for m in HOURS_RE.finditer(text):
        facts["时限"].add(f"{_num(m.group(1))}个工作日")
    return facts


def _num(raw: str) -> str:
    try:
        return f"{float(raw):g}"
    except ValueError:
        return raw


def scan(document: Document) -> list[Conflict]:
    """新文档 vs 在版文档的同事项数值差异。"""
    chunks = list(Chunk.objects.filter(document=document).values_list("content", flat=True))
    if not chunks:
        return []
    draft = _facts("\n".join(chunks))

    published = list(
        Document.objects.filter(status=PublishStatus.PUBLISHED).exclude(pk=document.pk)
    )
    peers = [doc for doc in published if _similar(doc.title, document.title)]
    if not peers:
        return []

    out: list[Conflict] = []
    for peer in peers:
        text = "\n".join(
            Chunk.objects.filter(document=peer).values_list("content", flat=True)
        )
        facts = _facts(text)
        for field in ("费用", "时限"):
            if len(draft[field]) != 1:
                continue                     # 新版自己就有多种说法，先让编辑理清
            mine = next(iter(draft[field]))
            for other in facts[field]:
                if other != mine:
                    out.append(
                        Conflict(
                            field=field,
                            draft_value=mine,
                            published_value=other,
                            published_doc=peer.title,
                            published_doc_id=peer.pk,
                        )
                    )
    return out
