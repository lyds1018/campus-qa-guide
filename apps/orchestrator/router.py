"""意图路由：决定这一轮"要不要拆、拆几段、走哪条路"。

路由只读 M5 的结果与会话状态，不调模型、不查库。
"""

from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings

from apps.orchestrator.session import SessionState
from apps.qa.types import Intent, Understanding

# 指代补全用：只认这几种明确的回指，"其他""其实"这类不算
PRONOUNS = ("这个", "那个", "该事项", "它", "这项", "上面说", "刚才说", "那要")

DIRECT = "direct"      # 寒暄 / 越界：不检索、不生成
SINGLE = "single"      # 单段：真流式
FANOUT = "fanout"      # 多子问题：并行、结果装配


@dataclass(frozen=True)
class Plan:
    mode: str
    segments: tuple[str, ...]
    reason: str


def enrich(question: str, state: SessionState) -> tuple[str, bool]:
    """指代补全：短问句 + 指代词 + 上一轮有事项时，把事项名补到问句前面。

    放在路由层而不是提示层，是因为它决定检索用的字符串——检索拿不到正确实体，
    后面再好的提示也救不回来。
    """
    if not state.last_matter or state.last_matter in question:
        return question, False
    if not any(p in question for p in PRONOUNS):
        return question, False
    # 只在短问句上补："这个学校的图书馆远不远"里的"这个"往往是新话题，
    # 补上去反而把两个事项糅在一起，长问句一律不动
    if len(question) > 10:
        return question, False
    return f"{state.last_matter}：{question}", True


def plan_for(understanding: Understanding, state: SessionState | None = None) -> Plan:
    if understanding.intent in (Intent.SMALLTALK, Intent.OUT_OF_SCOPE):
        return Plan(DIRECT, (understanding.original,), f"intent={understanding.intent.value}")

    subs: list[str] = []
    for sub in understanding.sub_questions:
        sub = (sub or "").strip()
        if not sub or sub == understanding.original or sub in subs:
            continue
        subs.append(sub)
    subs = subs[: settings.ORC_FANOUT_MAX]

    # 至少两个子问题才值得并行：一段拆成一段只是多花一次调用
    if len(subs) >= 2:
        return Plan(FANOUT, tuple(subs), f"sub_questions={len(subs)}")
    return Plan(SINGLE, (understanding.original,), "single")
