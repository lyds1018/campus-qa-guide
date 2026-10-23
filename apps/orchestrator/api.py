"""编排层接口。

`/turn` 与 `/stream` 是给 P5 用的两个入口：P5 在其上加鉴权、限流、审计，
本层只负责会话与协议。`/sessions` 是 P5 侧边栏（历史会话）的数据源。

POST + SSE（而不是 GET + EventSource）：问题在 body 里，长度不受 query 限制，
也不必把问句写进访问日志。前端用 fetch + ReadableStream 读，P5 的页面按这个写。
"""

from __future__ import annotations

from datetime import datetime

from django.http import StreamingHttpResponse
from ninja import Router, Schema

from apps.orchestrator import events, session
from apps.orchestrator.models import Conversation, Message
from apps.orchestrator.orchestrator import orc

router = Router(tags=["orc"])


class TurnIn(Schema):
    question: str
    conversation_id: str | None = None
    user_key: str = "demo"
    audience: str = "unknown"
    doc_types: list[str] | None = None


class SessionOut(Schema):
    id: str
    title: str
    audience: str
    turn_count: int
    last_active_at: datetime


class MessageOut(Schema):
    turn: int
    role: str
    content: str
    intent: str
    answerable: bool | None
    refusal_reason: str
    latency_ms: int
    created_at: datetime
    payload: dict


@router.post("/turn")
async def turn(request, payload: TurnIn):
    result = await orc.turn(
        payload.question,
        user_key=payload.user_key,
        conversation_id=payload.conversation_id,
        audience=payload.audience,
        doc_types=payload.doc_types,
    )
    return result.as_dict()


@router.post("/stream")
async def stream(request, payload: TurnIn):
    frames = orc.stream(
        payload.question,
        user_key=payload.user_key,
        conversation_id=payload.conversation_id,
        audience=payload.audience,
        doc_types=payload.doc_types,
    )
    response = StreamingHttpResponse(
        events.with_heartbeat(frames), content_type="text/event-stream"
    )
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"  # 让 Nginx 不要缓冲，否则首字被攒住
    return response


@router.get("/sessions", response=list[SessionOut])
def sessions(request, user_key: str = "demo", limit: int = 20):
    return [
        SessionOut(
            id=str(c.pk),
            title=c.title,
            audience=c.audience,
            turn_count=c.turn_count,
            last_active_at=c.last_active_at,
        )
        for c in session.recent(user_key, limit)
    ]


@router.get("/sessions/{conversation_id}", response=list[MessageOut])
def history(request, conversation_id: str):
    conv = Conversation.objects.filter(pk=conversation_id).first()
    if conv is None:
        return []
    return [
        MessageOut(
            turn=m.turn,
            role=m.role,
            content=m.content,
            intent=m.intent,
            answerable=m.answerable,
            refusal_reason=m.refusal_reason,
            latency_ms=m.latency_ms,
            created_at=m.created_at,
            payload=m.payload or {},
        )
        for m in Message.objects.filter(conversation=conv)
    ]


@router.delete("/sessions/{conversation_id}")
def reset(request, conversation_id: str):
    """只清上下文窗口，不删消息：留痕要还给 P7 复盘。"""
    session.clear(conversation_id)
    return {"conversation_id": conversation_id, "cleared": True}
