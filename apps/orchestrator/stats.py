"""在线问答统计：运营看板与评测页共用同一套口径。

两处页面问的是同一批 `messages`，分位数与拒答率的定义必须一致；此前各写一份，
后续很容易出现"看板 3.6s、评测 3.4s"这种口径漂移。离线评测的样本统计不在这里，
它评的是 `qa.answer`，不是落库消息。
"""

from __future__ import annotations

from datetime import datetime

from django.db.models import Count, QuerySet

from apps.orchestrator.models import Message


def _answers_since(since: datetime) -> QuerySet[Message]:
    return Message.objects.filter(role=Message.Role.ASSISTANT, created_at__gte=since)


def summarize(since: datetime, *, breakdown: bool = False) -> dict:
    """统计时间窗内的作答数、拒答率、P50/P95 与可选的意图分布。"""
    answers = _answers_since(since)
    total = answers.count()
    refused = answers.filter(answerable=False).count()
    latencies = sorted(answers.values_list("latency_ms", flat=True))

    data = {
        "turns": total,
        "refused": refused,
        "refusal_rate": round(refused / total * 100, 1) if total else 0.0,
        "p50_ms": latencies[len(latencies) // 2] if latencies else 0,
        "p95_ms": (
            latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))]
            if latencies
            else 0
        ),
    }
    if breakdown:
        data["intents"] = {
            row["intent"] or "unknown": row["n"]
            for row in answers.values("intent").annotate(n=Count("id"))
        }
        data["refusal_reasons"] = {
            row["refusal_reason"] or "(作答)": row["n"]
            for row in answers.values("refusal_reason").annotate(n=Count("id"))
        }
    return data
