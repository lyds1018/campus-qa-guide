"""反馈与评测留痕。

两张表分工：
- `feedback` 是**候选池**：用户点"没用"并选了原因，才值得人工看一眼、再决定要不要进黄金集；
- `eval_runs` 是**回归档案**：每次跑批/演练的指标与报告路径，用来对比"这次改动有没有变差"。
"""

from __future__ import annotations

from django.db import models


class Feedback(models.Model):
    class Rating(models.TextChoices):
        UP = "up", "有用"
        DOWN = "down", "没用"

    class Reason(models.TextChoices):
        WRONG_FACT = "wrong_fact", "口径/数字错"
        INCOMPLETE = "incomplete", "答不全"
        OFF_TOPIC = "off_topic", "答非所问"
        OUTDATED = "outdated", "信息过期"
        OTHER = "other", "其他"

    class Expect(models.TextChoices):
        ANSWER = "answer", "应可答"
        REFUSE = "refuse", "应拒答"
        UNSURE = "unsure", "说不清"

    user_key = models.CharField(max_length=64, db_index=True)
    conversation_id = models.CharField(max_length=36, blank=True, default="")
    trace_id = models.CharField(max_length=64, blank=True, default="")
    question = models.CharField(max_length=200)
    answer_excerpt = models.CharField(max_length=500, blank=True, default="")
    rating = models.CharField(max_length=8, choices=Rating.choices)
    reason = models.CharField(max_length=16, choices=Reason.choices, blank=True, default="")
    expect = models.CharField(max_length=8, choices=Expect.choices, blank=True, default="unsure")
    note = models.CharField(max_length=200, blank=True, default="")
    reviewed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "feedback"
        ordering = ["-id"]
        indexes = [
            models.Index(fields=["rating", "created_at"], name="idx_fb_rating_created"),
            models.Index(fields=["trace_id"], name="idx_fb_trace"),
        ]

    def __str__(self) -> str:
        return f"{self.rating} {self.question[:20]}"


class EvalRun(models.Model):
    class Kind(models.TextChoices):
        EVAL = "eval", "批量回归"
        DRILL = "drill", "降级演练"

    kind = models.CharField(max_length=8, choices=Kind.choices)
    label = models.CharField(max_length=80, blank=True, default="")
    samples = models.IntegerField(default=0)
    metrics = models.JSONField(default=dict)
    report_path = models.CharField(max_length=300, blank=True, default="")
    cost = models.DecimalField(max_digits=12, decimal_places=6, default=0)
    duration_ms = models.IntegerField(default=0)
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField()

    class Meta:
        db_table = "eval_runs"
        ordering = ["-id"]
        indexes = [models.Index(fields=["kind", "finished_at"], name="idx_eval_kind_finished")]

    def __str__(self) -> str:
        return f"{self.kind}#{self.pk} {self.label}"
