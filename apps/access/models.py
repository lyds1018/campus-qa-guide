"""接口访问留痕。

只记元数据，不记问句与答案：问句在 `messages` 里，正文进审计表只会让库变大、
把敏感内容分散到两处。要看内容去会话表，要看"谁在什么时候打了哪个接口"来这里。
"""

from __future__ import annotations

from django.db import models


class ApiLog(models.Model):
    id = models.BigAutoField(primary_key=True)
    trace_id = models.CharField(max_length=64, blank=True, default="")
    user_key = models.CharField(max_length=64, blank=True, default="")
    role = models.CharField(max_length=16, blank=True, default="")
    method = models.CharField(max_length=8)
    path = models.CharField(max_length=200)
    status = models.SmallIntegerField(default=0)
    latency_ms = models.IntegerField(default=0)
    ip = models.CharField(max_length=64, blank=True, default="")
    bucket = models.CharField(max_length=16, blank=True, default="")
    limited = models.BooleanField(default=False)
    error = models.CharField(max_length=200, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "api_logs"
        ordering = ["-id"]
        indexes = [
            models.Index(fields=["created_at"], name="idx_apilog_created"),
            models.Index(fields=["user_key", "created_at"], name="idx_apilog_user"),
            models.Index(fields=["path", "status"], name="idx_apilog_path_status"),
        ]

    def __str__(self) -> str:
        return f"{self.method} {self.path} {self.status}"
