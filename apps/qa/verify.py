"""M9 校验：引用核对、数值一致性、口径冲突、可答性判定。

这一层全部是确定性代码，不调模型。理由：判定"能不能答"和"引用对不对"如果用模型，
模型错一次就没有第二道防线了；而这三件事恰好都能用正则 + 集合运算做到可解释、可回归。
"""

from __future__ import annotations

import re

from django.conf import settings

from apps.qa.types import (
    Conflict,
    Evidence,
    Issue,
    RefusalReason,
    RetrievalResult,
    VerifyReport,
)

REF_RE = re.compile(r"\[(\d{1,2})\]")
SENT_SPLIT = re.compile(r"(?<=[。！？!?；;])|\n+")

# 语料里"三个工作日"与"3 个工作日"两种写法混用，两边都必须认，否则正确回答会被判成编造
NUMBER_RE = re.compile(
    r"(\d+(?:\.\d+)?|[一二三四五六七八九十两]{1,3})\s*"
    r"(个工作日|工作日|元|块|份|次|天|日|周|个月|月|年|%|小时|分钟|页|人|张)"
)
UNIT_NORMAL = {"块": "元", "日": "天", "个工作日": "工作日"}
CN_DIGITS = {
    "零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
}
# "一次性""一站式"里的"一次"不是数量
FALSE_NUM = re.compile(r"一次性|一站式|一次性告知")

# 一句话里有这些内容就必须带引用：数字、硬信息、办理动作
CITE_REQUIRED = (
    "材料", "地点", "窗口", "时间", "费用", "元", "工作日", "电话", "条件",
    "要求", "步骤", "线上", "线下", "自助", "份", "时限", "期限",
)
# 这几种句子是"承认不知道"，不要求引用
NO_CITE_OK = ("现有资料未涉及", "知识库未收录", "未涉及", "以原文为准")

COST_RE = re.compile(r"(\d+(?:\.\d+)?)\s*元\s*(?:/|每)?\s*(份|次|人|张|页)")
HOURS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:个)?工作日")

# 只有"同一事项"的跨文档数值才拿来比：不同事项的时限/费用天然不同，
# 跨事项比对必然误报，宁可漏检也不给用户制造假冲突。
TITLE_OVERLAP = 0.6


def extract_refs(text: str) -> list[int]:
    out: list[int] = []
    for m in REF_RE.finditer(text):
        ref = int(m.group(1))
        if ref not in out:
            out.append(ref)
    return out


def _cn_to_int(raw: str) -> str | None:
    """一 → 1、十二 → 12、三十五 → 35。百以上不认，语料里不会出现。"""
    if not any(ch in CN_DIGITS or ch == "十" for ch in raw):
        return None
    total, cur = 0, 0
    for ch in raw:
        if ch == "十":
            total += (cur or 1) * 10
            cur = 0
        elif ch in CN_DIGITS:
            cur = CN_DIGITS[ch]
        else:
            return None
    return f"{total + cur:g}"


def _normalize_num(raw: str) -> str:
    if raw.isdigit() or raw.replace(".", "", 1).isdigit():
        return f"{float(raw):g}"
    converted = _cn_to_int(raw)
    return converted if converted is not None else raw


def numbers_in(text: str) -> set[str]:
    """抽「数值+单位」对。中文数字（三个工作日）不参与核对，见文档已知限制。"""
    out: set[str] = set()
    text = FALSE_NUM.sub("单次", text)
    for m in NUMBER_RE.finditer(text):
        num = _normalize_num(m.group(1))
        unit = UNIT_NORMAL.get(m.group(2), m.group(2))
        out.add(f"{num}{unit}")
    return out


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in SENT_SPLIT.split(text) if s and s.strip()]


def _needs_cite(sentence: str) -> bool:
    if any(ok in sentence for ok in NO_CITE_OK):
        return False
    if REF_RE.search(sentence):
        return True
    return any(w in sentence for w in CITE_REQUIRED) or bool(NUMBER_RE.search(sentence))


def _title_similar(a: str, b: str) -> bool:
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return False
    return len(sa & sb) / min(len(sa), len(sb)) >= TITLE_OVERLAP


def detect_conflicts(evidence: list[Evidence]) -> list[Conflict]:
    """跨文档、同事项、同计量单位的数值差异 → 口径冲突。"""
    def _collect(pattern: re.Pattern[str], field: str, unit_of) -> list[Conflict]:
        found: dict[str, dict[int, set[str]]] = {}
        titles: dict[int, str] = {}
        for e in evidence:
            titles[e.ref] = e.title
            for m in pattern.finditer(e.content):
                key = unit_of(m)
                value = _normalize_num(m.group(1))
                found.setdefault(key, {}).setdefault(e.ref, set()).add(value)

        out: list[Conflict] = []
        for key, per_ref in found.items():
            refs = list(per_ref)
            if len(refs) < 2:
                continue
            if not any(
                _title_similar(titles[a], titles[b])
                for i, a in enumerate(refs)
                for b in refs[i + 1 :]
            ):
                continue
            values = {v for vs in per_ref.values() for v in vs}
            if len(values) < 2:
                continue
            out.append(
                Conflict(
                    field=f"{field}（每{key}）" if key else field,
                    values=[
                        f"{v}{'元' if field == '费用' else '个工作日'}"
                        for v in sorted(values)
                    ],
                    refs=refs,
                )
            )
        return out

    conflicts = _collect(COST_RE, "费用", lambda m: m.group(2))
    conflicts += _collect(HOURS_RE, "时限", lambda m: "")
    return conflicts


def check(text: str, evidence: list[Evidence], conflicts: list[Conflict]) -> VerifyReport:
    """回答体的核对。任何 blocking 问题都要么重写一次，要么降级为"未核实"。"""
    refs = extract_refs(text)
    valid = {e.ref for e in evidence}
    bad_refs = [r for r in refs if r not in valid]

    evidence_numbers = numbers_in("\n".join(e.content for e in evidence))
    unverified = sorted(numbers_in(text) - evidence_numbers)

    needed = [s for s in split_sentences(text) if _needs_cite(s)]
    cited = [s for s in needed if REF_RE.search(s)]
    coverage = len(cited) / len(needed) if needed else 1.0

    issues: list[Issue] = []
    if not refs:
        issues.append(Issue("no_citation", "回答没有任何引用编号", blocking=True))
    if bad_refs:
        issues.append(
            Issue("bad_ref", f"引用了不存在的编号 {bad_refs}（有效范围 1-{len(evidence)}）", True)
        )
    if unverified:
        issues.append(
            Issue("unverified_number", f"这些数值在证据里找不到：{'、'.join(unverified)}", True)
        )
    if coverage < settings.QA_MIN_CITATION_COVERAGE:
        issues.append(
            Issue(
                "low_coverage",
                f"需要引用的句子只有 {coverage:.0%} 带了引用（要求 ≥ "
                f"{settings.QA_MIN_CITATION_COVERAGE:.0%}）",
                True,
            )
        )
    for c in conflicts:
        missing = [v for v in c.values if v not in text and v.replace("元", "") not in text]
        if missing:
            issues.append(
                Issue(
                    "conflict_not_surfaced",
                    f"{c.field}存在不同说法（{'、'.join(c.values)}），回答里必须并列说明",
                    True,
                )
            )

    return VerifyReport(
        ok=not any(i.blocking for i in issues),
        citation_coverage=coverage,
        refs=refs,
        bad_refs=bad_refs,
        unverified_numbers=unverified,
        issues=issues,
    )


def gate(result: RetrievalResult) -> RefusalReason | None:
    """可答性判定：检索侧的门槛结论翻译成拒答口径。"""
    if result.answerable:
        return None
    if result.reason == "no_evidence":
        return RefusalReason.NO_EVIDENCE
    return RefusalReason.LOW_CONFIDENCE
