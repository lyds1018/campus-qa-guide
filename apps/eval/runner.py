"""批量回归的执行与打分。

评测对象是 `qa.answer`（能力层），不是 `orc.turn`（会话层）：P7 要回答的是
"同一批问题，答得还对不对"，会话状态、SSE 装配不是被评对象，也不该在评测里往
`messages` 写脏数据。会话层有自己的单测。

一次回归的口径：
- 逐条跑黄金集，记录是否作答、置信/拒答原因、命中前 3 的文档、关键词命中、引用问题；
- 延迟取每条的端到端耗时（含理解 + 检索 + 生成）；
- 成本取跑批窗口内 `ai_calls.cost` 之和（跑前跑后各 flush 一次，避免缓冲漏账）。
"""

from __future__ import annotations

import json
import statistics
import time
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from apps.gateway import meter
from apps.gateway.models import AICall
from apps.qa.pipeline import qa

GOLDEN = Path(__file__).resolve().parents[1] / "qa" / "fixtures" / "golden.jsonl"

# 达标线：低于它就写进报告的"未达标"一栏，不靠人眼看
TARGETS = {
    "hit_at_3": 0.90,
    "answer_ok": 0.90,
    "refuse_ok": 0.90,
    "must_ok": 0.90,
    "verified_rate": 0.90,
    "citation_rate": 0.70,
}


@dataclass
class Sample:
    q: str
    expect: str
    intent_expect: str
    intent: str = ""
    answerable: bool = False
    refusal_reason: str = ""
    doc_hit: bool | None = None
    doc_titles: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    citations: int = 0
    latency_ms: int = 0
    answerable_ok: bool = False
    degraded: bool = False
    text_head: str = ""

    def as_dict(self) -> dict:
        return {
            "q": self.q,
            "expect": self.expect,
            "intent_expect": self.intent_expect,
            "intent": self.intent,
            "answerable": self.answerable,
            "refusal_reason": self.refusal_reason,
            "doc_hit": self.doc_hit,
            "doc_titles": self.doc_titles[:3],
            "missing": self.missing,
            "issues": self.issues,
            "citations": self.citations,
            "latency_ms": self.latency_ms,
            "answerable_ok": self.answerable_ok,
            "degraded": self.degraded,
            "text_head": self.text_head[:120],
        }


def load_rows(path: Path | None = None) -> list[dict]:
    path = path or GOLDEN
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("//"):
            rows.append(json.loads(line))
    return rows


def _check(row: dict, answer) -> Sample:
    sample = Sample(
        q=row["q"],
        expect=row.get("expect", "answer"),
        intent_expect=row.get("intent", ""),
        intent=answer.intent,
        answerable=answer.answerable,
        refusal_reason=answer.refusal_reason or "",
        latency_ms=answer.latency_ms,
        citations=len(answer.citations),
        degraded=answer.degraded,
        text_head=(answer.text or "").replace("\n", " "),
    )
    titles = []
    for item in answer.evidence:
        if item.title not in titles:
            titles.append(item.title)
    sample.doc_titles = titles
    if row.get("doc"):
        sample.doc_hit = any(row["doc"] in t for t in titles[:3])
    # 关键词只在"真的作答"时才有意义：拒答里出现关键词不算答对
    if answer.answerable:
        sample.missing = [m for m in row.get("must", []) if m not in answer.text]
    elif row.get("must"):
        sample.missing = list(row["must"])
    if answer.checks:
        sample.issues = [i.code for i in answer.checks.blocking]
    sample.answerable_ok = (
        answer.answerable if sample.expect != "refuse" else not answer.answerable
    )
    return sample


async def run_samples(
    rows: list[dict], *, audience: str = "unknown", progress=None
) -> list[Sample]:
    out: list[Sample] = []
    for index, row in enumerate(rows, 1):
        started = time.monotonic()
        answer = await qa.answer(row["q"], audience=audience)
        # 用真实墙钟校正一次：answer.latency_ms 不含排队与序列化
        answer.latency_ms = max(answer.latency_ms, int((time.monotonic() - started) * 1000))
        sample = _check(row, answer)
        out.append(sample)
        if progress is not None:
            progress(index, len(rows), sample)
    return out


def _rate(hit: int, total: int) -> float:
    return round(hit / total, 3) if total else 0.0


def summarize(samples: list[Sample]) -> dict:
    answered = [s for s in samples if s.answerable]
    answer_rows = [s for s in samples if s.expect != "refuse"]
    refuse_rows = [s for s in samples if s.expect == "refuse"]
    doc_rows = [s for s in samples if s.doc_hit is not None]
    latencies = sorted(s.latency_ms for s in samples)

    return {
        "samples": len(samples),
        "answered": len(answered),
        "refused": len(samples) - len(answered),
        "answer_ok": _rate(sum(1 for s in answer_rows if s.answerable_ok), len(answer_rows)),
        "refuse_ok": _rate(sum(1 for s in refuse_rows if s.answerable_ok), len(refuse_rows)),
        "hit_at_3": _rate(sum(1 for s in doc_rows if s.doc_hit), len(doc_rows)),
        "must_ok": _rate(sum(1 for s in samples if not s.missing), len(samples)),
        "citation_rate": _rate(sum(1 for s in answered if s.citations), len(answered)),
        "verified_rate": _rate(sum(1 for s in answered if not s.issues), len(answered)),
        "latency_p50_ms": latencies[len(latencies) // 2] if latencies else 0,
        "latency_p95_ms": latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))]
        if latencies
        else 0,
        "n_answer": len(answer_rows),
        "n_refuse": len(refuse_rows),
        "n_doc": len(doc_rows),
        "n_answered": len(answered),
        "intent_acc": _rate(
            sum(
                1
                for s in samples
                if s.intent_expect and s.intent and s.intent == s.intent_expect
            ),
            sum(1 for s in samples if s.intent_expect),
        ),
    }


# 分母为 0 的指标一律不判：小样本试跑（--limit 5）里没有拒答样本，
# 若按 0% 判"未达标"，报告会天天报红，人就不看了。
DENOMINATOR = {
    "answer_ok": "n_answer",
    "refuse_ok": "n_refuse",
    "hit_at_3": "n_doc",
    "cited": "n_answered",
    "citation_rate": "n_answered",
    "verified_rate": "n_answered",
}


def targets_of(summary: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for key, target in TARGETS.items():
        if key not in summary:
            continue
        denom = summary.get(DENOMINATOR.get(key, ""), None)
        if denom == 0:
            continue
        out[key] = {"value": summary[key], "target": target, "ok": summary[key] >= target}
    return out


def cost_since(started_at: datetime) -> Decimal:
    """跑批窗口内的模型花费。调用前请先 flush，否则缓冲里的账还没落库。"""
    meter.flush_sync()
    rows = AICall.objects.filter(created_at__gte=started_at, cached=False)
    return sum((row.cost for row in rows), Decimal("0"))


def env_snapshot() -> dict:
    from apps.knowledge.models import Chunk, Document, Matter, PublishStatus

    return {
        "documents": Document.objects.filter(status=PublishStatus.PUBLISHED).count(),
        "chunks": Chunk.objects.filter(status=PublishStatus.PUBLISHED).count(),
        "embedded": Chunk.objects.exclude(embedding=None).count(),
        "matters": Matter.objects.count(),
        "main_model": settings.GW_CHAT_MAIN_MODEL,
        "embed_model": settings.GW_EMBED_MODEL,
        "rerank_model": settings.GW_RERANK_MODEL,
        "at": timezone.now().strftime("%Y-%m-%d %H:%M"),
    }


def markdown_report(
    *, summary: dict, samples: list[Sample], label: str, cost: Decimal, cost_note: str = ""
) -> str:
    env = env_snapshot()
    lines = [
        f"# 评测报告 · {label or '默认'}",
        "",
        f"- 生成时间：{env['at']}",
        f"- 语料：{env['documents']} 在版文档 / {env['chunks']} 块（已向量 {env['embedded']}）"
        f" / {env['matters']} 事项",
        f"- 模型：main `{env['main_model']}`、embed `{env['embed_model']}`、"
        f"rerank `{env['rerank_model']}`",
        f"- 成本：¥{cost:.4f}{cost_note}",
        "",
        "## 一、总览",
        "",
        "| 指标 | 值 | 达标线 | 结论 |",
        "| --- | --- | --- | --- |",
    ]
    for key, item in targets_of(summary).items():
        name = {
            "hit_at_3": "期望文档进 top3",
            "answer_ok": "应可答判对",
            "refuse_ok": "应拒答判对",
            "must_ok": "关键词命中",
            "verified_rate": "校验通过",
            "citation_rate": "引用覆盖率",
        }.get(key, key)
        flag = "达标" if item["ok"] else "**未达标**"
        lines.append(f"| {name} | {item['value']:.0%} | {item['target']:.0%} | {flag} |")

    lines += [
        "",
        f"- 样本 {summary['samples']} 条：作答 {summary['answered']}、拒答 {summary['refused']}",
        f"- 延迟 P50 {summary['latency_p50_ms']}ms / P95 {summary['latency_p95_ms']}ms",
        f"- 意图准确率 {summary['intent_acc']:.0%}",
        "",
        "## 二、未通过样本",
        "",
    ]

    failed = [
        s
        for s in samples
        if not s.answerable_ok or s.missing or s.doc_hit is False or s.issues
    ]
    if not failed:
        lines.append("无。")
    else:
        lines += [
            "| 问题 | 期望 | 实际 | 拒答原因 | 命中 | 缺失关键词 / 问题 |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for s in failed[:30]:
            detail = "、".join(s.missing) or "、".join(s.issues) or "-"
            hit = "是" if s.doc_hit else ("否" if s.doc_hit is False else "-")
            state = "作答" if s.answerable else "未作答"
            lines.append(
                f"| {s.q} | {s.expect} | {state} | {s.refusal_reason or '-'} | {hit} | {detail} |"
            )
        if len(failed) > 30:
            lines.append(f"| … 另有 {len(failed) - 30} 条 | | | | | |")

    lines += [
        "",
        "## 三、口径说明",
        "",
        "- 评测对象是 `qa.answer()`（能力层），不含会话与 SSE 装配；后者由 P4 单测覆盖。",
        "- 「应可答判对」= 期望作答且 `answerable=true`；「应拒答判对」= 期望拒答且未作答。",
        "- 「关键词命中」在拒答样本上按未命中计：拒答话术里出现关键词不算答对。",
        "- 延迟是端到端墙钟；热缓存（同一问句二次调用）会显著偏低，对比时须看是否清过缓存。",
    ]
    return "\n".join(lines) + "\n"


def write_report(text: str, *, label: str) -> Path:
    folder = Path(settings.EVAL_REPORT_DIR)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = timezone.localtime().strftime("%Y%m%d-%H%M%S")
    safe = "".join(c for c in (label or "eval") if c.isalnum() or c in "-_") or "eval"
    path = folder / f"{stamp}-{safe}.md"
    path.write_text(text, encoding="utf-8")
    return path


def median(values: list[int]) -> int:
    return int(statistics.median(values)) if values else 0
