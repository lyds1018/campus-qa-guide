"""评测与反馈的只读接口（挂在 `/api/ops` 下，管理员 token）。

跑批与演练不开放 HTTP：它们会真调模型、耗时几十秒，属于运维动作。
和 P2 的"清理类动作走命令行"是同一条口径。
"""

from __future__ import annotations

from datetime import datetime, timedelta

from django.db.models import Count
from django.utils import timezone
from ninja import Router, Schema

from apps.eval import runner
from apps.eval.models import EvalRun, Feedback
from apps.orchestrator import stats

router = Router(tags=["ops"])


class FeedbackOut(Schema):
    id: int
    question: str
    answer_excerpt: str
    rating: str
    reason: str
    expect: str
    note: str
    user_key: str
    trace_id: str
    created_at: datetime


class RunOut(Schema):
    id: int
    kind: str
    label: str
    samples: int
    metrics: dict
    report_path: str
    cost: float
    duration_ms: int
    finished_at: datetime


class MetricsOut(Schema):
    days: int
    qa: dict
    feedback: dict
    evals: list[dict]
    golden: dict
    env: dict


@router.get("/feedback", response=list[FeedbackOut])
def feedback(request, rating: str = "", limit: int = 50):
    qs = Feedback.objects.all()
    if rating:
        qs = qs.filter(rating=rating)
    return [
        FeedbackOut(
            id=row.pk,
            question=row.question,
            answer_excerpt=row.answer_excerpt,
            rating=row.rating,
            reason=row.reason,
            expect=row.expect,
            note=row.note,
            user_key=row.user_key,
            trace_id=row.trace_id,
            created_at=row.created_at,
        )
        for row in qs[: max(1, min(limit, 200))]
    ]


@router.get("/evals", response=list[RunOut])
def evals(request, kind: str = "", limit: int = 20):
    qs = EvalRun.objects.all()
    if kind:
        qs = qs.filter(kind=kind)
    return [
        RunOut(
            id=row.pk,
            kind=row.kind,
            label=row.label,
            samples=row.samples,
            metrics=row.metrics,
            report_path=row.report_path,
            cost=float(row.cost),
            duration_ms=row.duration_ms,
            finished_at=row.finished_at,
        )
        for row in qs[: max(1, min(limit, 100))]
    ]


@router.get("/metrics", response=MetricsOut)
def metrics(request, days: int = 7):
    days = max(1, min(days, 90))
    since = timezone.now() - timedelta(days=days)
    qa = stats.summarize(since, breakdown=True)

    fb = Feedback.objects.filter(created_at__gte=since)
    fb_total = fb.count()
    fb_down = fb.filter(rating=Feedback.Rating.DOWN).count()
    fb_reasons = {
        row["reason"] or "unspecified": row["n"]
        for row in fb.filter(rating=Feedback.Rating.DOWN).values("reason").annotate(n=Count("id"))
    }

    runs = [
        {
            "id": r.pk,
            "kind": r.kind,
            "label": r.label,
            "samples": r.samples,
            "metrics": r.metrics,
            "finished_at": r.finished_at,
        }
        for r in EvalRun.objects.all()[:20]
    ]

    try:
        rows = runner.load_rows()
        golden = {
            "samples": len(rows),
            "answer": sum(1 for r in rows if r.get("expect", "answer") != "refuse"),
            "refuse": sum(1 for r in rows if r.get("expect") == "refuse"),
            "with_doc": sum(1 for r in rows if r.get("doc")),
        }
    except OSError:
        golden = {"samples": 0, "answer": 0, "refuse": 0, "with_doc": 0}

    return MetricsOut(
        days=days,
        qa=qa,
        feedback={
            "total": fb_total,
            "down": fb_down,
            "down_rate": round(fb_down / fb_total * 100, 1) if fb_total else 0.0,
            "reasons": fb_reasons,
        },
        evals=runs,
        golden=golden,
        env=runner.env_snapshot(),
    )
