"""会话与消息两张表。

分工先钉死：**Redis 存热状态（上下文窗口、槽位、上一轮事项），PG 存留痕**。
Redis 丢了不影响事实——重建会话只是丢掉指代能力；PG 丢了就没有历史会话列表。

不存"答案全文的副本"以外的任何东西：引用、清单、证据都进 `payload`，
P5 的回放与 P7 的复盘都读它，不再反查 P3。
"""

from __future__ import annotations

import uuid

from django.db import models


class Conversation(models.Model):
    """一次会话。id 由服务端生成，前端拿它续聊（不需要登录态）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user_key = models.CharField(max_length=64, db_index=True)
    title = models.CharField(max_length=120, blank=True, default="")
    audience = models.CharField(max_length=16, blank=True, default="unknown")
    turn_count = models.PositiveIntegerField(default=0)
    last_active_at = models.DateTimeField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "conversations"
        ordering = ["-last_active_at"]
        indexes = [models.Index(fields=["user_key", "last_active_at"], name="idx_conv_user_active")]

    def __str__(self) -> str:
        return f"{self.id} {self.title[:20]}"


class Message(models.Model):
    """一问一答各一行。assistant 行的 payload 存整份 TurnResult。"""

    class Role(models.TextChoices):
        USER = "user", "用户"
        ASSISTANT = "assistant", "助手"

    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="messages"
    )
    turn = models.PositiveIntegerField()
    role = models.CharField(max_length=16, choices=Role.choices)
    content = models.TextField()
    intent = models.CharField(max_length=24, blank=True, default="")
    answerable = models.BooleanField(null=True, blank=True)
    refusal_reason = models.CharField(max_length=24, blank=True, default="")
    trace_id = models.CharField(max_length=64, blank=True, default="")
    latency_ms = models.IntegerField(default=0)
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "messages"
        ordering = ["conversation_id", "turn", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["conversation", "turn", "role"], name="uq_msg_conv_turn_role"
            ),
        ]
        indexes = [
            models.Index(fields=["conversation", "turn"], name="idx_msg_conv_turn"),
            models.Index(fields=["trace_id"], name="idx_msg_trace"),
        ]

    def __str__(self) -> str:
        return f"{self.conversation_id}#{self.turn} {self.role}"
