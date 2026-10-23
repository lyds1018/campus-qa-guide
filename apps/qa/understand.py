"""M5 语言理解：意图分类、查询改写、别名映射、身份识别、缺失信息。

主路径是 aux 小模型一次结构化调用（gateway.chat_json），失败退规则。
规则不是"备用方案"，而是口径兜底：模型挂掉时系统仍能回答，评测里区分两种来源。
"""

from __future__ import annotations

import asyncio
from typing import Literal

from django.conf import settings
from pydantic import BaseModel, Field

from apps.gateway.base import ChatMessage, GatewayError
from apps.gateway.gateway import gateway
from apps.qa import lexicon, prompts
from apps.qa.types import Intent, Understanding

SMALLTALK_HINTS = (
    "你好", "您好", "在吗", "你是谁", "你叫什么", "你能做什么", "能干什么",
    "介绍一下你", "谢谢你", "谢谢", "再见", "嗨", "hello", "hi",
)
OUT_OF_SCOPE_HINTS = (
    "天气", "股票", "基金", "彩票", "汇率", "翻译", "写一篇", "写个", "写代码", "编程",
    "python", "java", "代码", "爬虫", "写一段", "小说", "笑话", "旅游", "减肥",
    "星座", "算命", "电影", "游戏攻略", "菜谱", "附近哪家",
)
MATTER_HINTS = (
    "怎么", "如何", "流程", "材料", "办理", "补办", "申请", "手续", "步骤",
    "去哪", "哪里办", "预约", "领取", "换", "注销",
)
POLICY_HINTS = (
    "规定", "办法", "细则", "制度", "标准", "允许", "条件", "资格", "认定",
    "评定", "比例", "限额", "处罚", "违规", "是否", "能不能", "可不可以",
)
FAQ_HINTS = ("多久", "什么时候", "几点", "在哪", "电话", "多少钱", "开放时间", "能不能用")


class UnderstandOut(BaseModel):
    """aux 模型的结构化输出。字段全部有默认值，避免一次缺字段就整次失败。"""

    intent: Literal["matter", "policy", "faq", "smalltalk", "out_of_scope"] = "faq"
    rewritten: str = ""
    audience: Literal["undergrad", "grad", "staff", "alumni", "unknown"] = "unknown"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    keyword: str = ""
    sub_questions: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)


def rules_intent(text: str) -> Intent:
    """规则判定。优先级：寒暄 → 越界 → 事项 → 制度 → 常见问题。"""
    low = text.lower()
    if any(h in low for h in SMALLTALK_HINTS):
        return Intent.SMALLTALK
    if any(h in low for h in OUT_OF_SCOPE_HINTS):
        return Intent.OUT_OF_SCOPE
    if any(h in low for h in MATTER_HINTS):
        return Intent.MATTER
    if any(h in low for h in POLICY_HINTS):
        return Intent.POLICY
    if any(h in low for h in FAQ_HINTS):
        return Intent.FAQ
    return Intent.MATTER


def _history_text(history: list[tuple[str, str]] | None) -> str:
    if not history:
        return "（无）"
    turns = history[-settings.QA_HISTORY_TURNS :]
    lines = [f"{'用户' if role == 'user' else '助手'}：{content}" for role, content in turns]
    return "\n".join(lines)


def _fallback(original: str, rewritten: str, audience: str) -> Understanding:
    return Understanding(
        intent=rules_intent(original),
        original=original,
        rewritten=rewritten,
        audience=audience,
        confidence=0.0,
        keyword=lexicon.keyword(rewritten),
        source="rules",
        missing=[],
    )


async def understand(
    question: str,
    *,
    audience: str = "unknown",
    history: list[tuple[str, str]] | None = None,
) -> Understanding:
    original = question.strip()
    # 词典改写要查库（可能落到 Redis 缓存），async 上下文里必须切线程
    rewritten_rule, hits = await asyncio.to_thread(lexicon.rewrite, original)
    audience_rule = lexicon.audience_of(original)
    known_audience = audience if audience not in ("", "unknown", None) else audience_rule

    messages = [
        ChatMessage("system", prompts.render("understand.system")),
        ChatMessage(
            "user",
            prompts.render(
                "understand.user",
                history=_history_text(history),
                question=original,
                audience=known_audience or "unknown",
            ),
        ),
    ]
    try:
        out: UnderstandOut = await gateway.chat_json(messages, schema=UnderstandOut, role="aux")
    except GatewayError:
        return _fallback(original, rewritten_rule, known_audience or "unknown")

    rewritten = (out.rewritten or "").strip() or rewritten_rule
    # 词典口径优先：模型可能把规范名改回口语，这里再套一遍
    if hits:
        rewritten = (await asyncio.to_thread(lexicon.rewrite, rewritten))[0]

    intent = Intent(out.intent)
    # 越界话题以规则为准：模型偶尔会把"天气怎么样"判成常见问题，
    # 一旦放行就会拿校园文档硬答，这类错答比拒答难看得多。
    if rules_intent(original) is Intent.OUT_OF_SCOPE and intent is not Intent.SMALLTALK:
        intent = Intent.OUT_OF_SCOPE

    missing = [m for m in out.missing if m][:3]
    if out.intent in ("matter", "policy") and len(lexicon.lexemes(rewritten)) < 2 and not missing:
        missing = ["具体事项名称或办理环节"]

    # "unknown" 是字符串真值，不能直接 or，否则模型识别出的身份永远被它盖掉
    final_audience = (
        known_audience if known_audience not in ("", "unknown", None) else out.audience
    )
    return Understanding(
        intent=intent,
        original=original,
        rewritten=rewritten,
        audience=final_audience,
        confidence=out.confidence,
        keyword=out.keyword or lexicon.keyword(rewritten),
        sub_questions=[q.strip() for q in out.sub_questions if q.strip()][:3],
        missing=missing,
        source="llm",
    )
