"""调用台账。网关每调一次模型就落一行，是 P7 成本与延迟指标的唯一来源。

写入走 meter.py 的进程内缓冲批量 flush，本表不参与主链路的同步写。
"""

from __future__ import annotations

from django.db import models


class CallTask(models.TextChoices):
    CHAT = "chat", "对话"
    EMBEDDING = "embedding", "嵌入"
    RERANK = "rerank", "重排"


class CallStatus(models.TextChoices):
    OK = "ok", "成功"
    DEGRADED = "degraded", "降级成功"
    FAILED = "failed", "失败"
    TIMEOUT = "timeout", "超时"
    BLOCKED = "blocked", "内容拦截"


class AICall(models.Model):
    trace_id = models.UUIDField()
    task = models.CharField(max_length=16, choices=CallTask.choices)
    provider = models.CharField(max_length=32)  # 槽位名 main / fallback / aux / embed / rerank
    model = models.CharField(max_length=80)
    status = models.CharField(max_length=16, choices=CallStatus.choices, default=CallStatus.OK)
    attempt = models.SmallIntegerField(default=1)
    cached = models.BooleanField(default=False)
    stream = models.BooleanField(default=False)
    prompt_tokens = models.IntegerField(default=0)
    completion_tokens = models.IntegerField(default=0)
    latency_ms = models.IntegerField(default=0)
    first_token_ms = models.IntegerField(null=True, blank=True)
    cost = models.DecimalField(max_digits=12, decimal_places=6, default=0)
    error_code = models.CharField(max_length=40, blank=True, default="")
    error_msg = models.TextField(blank=True, default="")
    meta = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ai_calls"
        indexes = [
            models.Index(fields=["created_at"], name="idx_call_created"),
            models.Index(fields=["task", "created_at"], name="idx_call_task_created"),
            models.Index(fields=["trace_id"], name="idx_call_trace"),
            models.Index(
                fields=["created_at"],
                name="idx_call_not_ok",
                condition=models.Q(status__in=["failed", "timeout", "blocked"]),
            ),
        ]
        ordering = ["-id"]

    def __str__(self) -> str:
        return f"{self.task}#{self.id} {self.provider}/{self.model} {self.status}"


class ModelSetting(models.Model):
    """模型槽位覆盖。

P6 的运营界面改这张表，不改 `.env`：改文件要重启进程，而且多实例各改各的。
**密钥不进这张表**：key 留在 `.env`，这里只覆盖 base_url 与模型名。
    """

    SLOTS = ("main", "fallback", "aux", "embed", "rerank")

    slot = models.CharField(max_length=16, unique=True)
    base_url = models.CharField(max_length=200, blank=True, default="")
    model = models.CharField(max_length=80, blank=True, default="")
    enabled = models.BooleanField(default=True)
    note = models.CharField(max_length=200, blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "model_settings"
        ordering = ["slot"]

    def __str__(self) -> str:
        return f"{self.slot} → {self.model or '(跟随 .env)'}"
