"""M8 生成：证据装配、提示构造、流式生成、引用锚标注。

提示是本层唯一的"口径来源"。网关（P2）只负责把这段文本送出去，不改一个字符；
所以答案长什么样、引用怎么写、什么情况拒答，全部在这里定。
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from dataclasses import dataclass

from django.conf import settings

from apps.gateway.base import ChatMessage, ChatParams
from apps.gateway.gateway import gateway
from apps.qa import prompts
from apps.qa.types import Conflict, Evidence, MatterMatch, Slots, Understanding

AUDIENCE_LABEL = {
    "undergrad": "本科生",
    "grad": "研究生",
    "staff": "教职工",
    "alumni": "毕业生/校友",
    "unknown": "未说明",
}

# 模型偶尔用全角括号或加空格，统一成 [n]，否则 M9 数不到引用
BRACKET_RE = re.compile(r"[［【\[]\s*(\d{1,2})\s*[］】\]]")
MD_HEAD_RE = re.compile(r"^#{1,6}\s*", re.MULTILINE)


@dataclass
class Generation:
    text: str
    model: str
    provider: str
    degraded: bool


def format_evidence(evidence: list[Evidence]) -> str:
    blocks = []
    for e in evidence:
        body = e.content.strip()
        blocks.append(f"[{e.ref}] {e.label}\n{body}")
    return "\n\n".join(blocks)


def format_conflict(conflicts: list[Conflict]) -> str:
    if not conflicts:
        return ""
    lines = ["【口径冲突：以下字段在证据里有不同说法，必须并列说明，不许择一】"]
    for c in conflicts:
        refs = "".join(f"[{r}]" for r in c.refs)
        lines.append(f"- {c.field}：{'、'.join(c.values)}（出处 {refs}）")
    return "\n".join(lines) + "\n"


def format_matter(matter: MatterMatch | None) -> str:
    if matter is None:
        return "未命中事项库"
    bits = [f"{matter.name}（{matter.dept or '部门未标注'}）"]
    if matter.location:
        bits.append(f"地点：{matter.location}")
    if matter.contact:
        bits.append(f"联系：{matter.contact}")
    return "；".join(bits)


def build_messages(
    question: str,
    understanding: Understanding,
    evidence: list[Evidence],
    *,
    matter: MatterMatch | None = None,
    slots: Slots | None = None,
    conflicts: list[Conflict] | None = None,
) -> list[ChatMessage]:
    slots = slots or Slots()
    user = prompts.render(
        "answer.user",
        audience=AUDIENCE_LABEL.get(slots.audience, slots.audience),
        question=question,
        rewritten=understanding.rewritten,
        intent=understanding.intent.value,
        matter=format_matter(matter),
        slots=f"渠道={slots.channel}，紧急度={slots.urgency}",
        conflict_block=format_conflict(conflicts or []),
        evidence=format_evidence(evidence),
    )
    return [
        ChatMessage("system", prompts.render("answer.system")),
        ChatMessage("user", user),
    ]


def build_repair_messages(
    base: list[ChatMessage], answer: str, issues: list[str]
) -> list[ChatMessage]:
    detail = "\n".join(f"- {i}" for i in issues)
    return [
        *base,
        ChatMessage("assistant", answer),
        ChatMessage("user", prompts.render("repair.user", issues=detail, answer=answer)),
    ]


def normalize(text: str) -> str:
    """引用锚归一 + 去掉模型自带的 Markdown 标题与加粗。"""
    text = BRACKET_RE.sub(lambda m: f"[{m.group(1)}]", text)
    text = MD_HEAD_RE.sub("", text)
    text = text.replace("**", "")
    return text.strip()


def _params() -> ChatParams:
    return ChatParams(
        temperature=settings.QA_ANSWER_TEMPERATURE,
        max_tokens=settings.QA_ANSWER_MAX_TOKENS,
    )


async def generate(messages: list[ChatMessage], *, trace_id: str | None = None) -> Generation:
    result = await gateway.chat(messages, role="main", params=_params(), trace_id=trace_id)
    return Generation(
        text=normalize(result.text),
        model=result.model,
        provider=result.provider,
        degraded=result.degraded,
    )


async def generate_stream(
    messages: list[ChatMessage], *, trace_id: str | None = None
) -> AsyncIterator[str]:
    """逐段吐字。断流由网关抛 StreamInterrupted，这里不吞异常。"""
    async for delta in gateway.chat_stream(
        messages, role="main", params=_params(), trace_id=trace_id
    ):
        if delta.text:
            yield delta.text
