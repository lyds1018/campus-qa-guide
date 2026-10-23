"""学生端接口（M1 的服务端）。

与 `/api/orc/*` 的区别：这里是**对外**出口，带身份、限流、审计；`/api/orc/*` 是
内部面（评测、排障用），生产应由 Nginx 只对内网开放。两者共用同一个编排器。
"""

from __future__ import annotations

import csv
import io
from datetime import datetime

from django.http import HttpResponse, StreamingHttpResponse
from ninja import Router, Schema

from apps.access import limit as rate
from apps.orchestrator import events
from apps.orchestrator.models import Conversation, Message
from apps.orchestrator.orchestrator import orc

router = Router(tags=["chat"])


class TurnIn(Schema):
    question: str
    conversation_id: str | None = None
    audience: str = ""


class ExportItem(Schema):
    kind: str
    text: str
    checked: bool = False


class ExportIn(Schema):
    title: str = "办事清单"
    question: str = ""
    items: list[ExportItem] = []


class MeOut(Schema):
    user_key: str
    audience: str
    role: str
    limits: dict


@router.get("/me", response=MeOut)
def me(request):
    who = request.identity
    buckets = {
        "chat": rate.limit_of(rate.CHAT),
        "write": rate.limit_of(rate.WRITE),
        "read": rate.limit_of(rate.READ),
    }
    return MeOut(user_key=who.user_key, audience=who.audience, role=who.role, limits=buckets)


@router.post("/turn")
async def turn(request, payload: TurnIn):
    who = request.identity
    result = await orc.turn(
        payload.question,
        user_key=who.user_key,
        conversation_id=payload.conversation_id,
        audience=payload.audience or who.audience,
        trace_id=request.trace_id,
    )
    return result.as_dict()


@router.post("/stream")
async def stream(request, payload: TurnIn):
    who = request.identity
    frames = orc.stream(
        payload.question,
        user_key=who.user_key,
        conversation_id=payload.conversation_id,
        audience=payload.audience or who.audience,
        trace_id=request.trace_id,
    )
    response = StreamingHttpResponse(
        events.with_heartbeat(frames), content_type="text/event-stream"
    )
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"   # Nginx 缓冲会让首字晚到
    return response


@router.get("/sessions")
def sessions(request, limit: int = 20):
    """只返回自己的会话：身份来自中间件，不接受前端传 user_key。"""
    who = request.identity
    rows = Conversation.objects.filter(user_key=who.user_key)[: max(1, min(limit, 50))]
    return [
        {
            "id": str(c.pk),
            "title": c.title,
            "turn_count": c.turn_count,
            "last_active_at": c.last_active_at,
        }
        for c in rows
    ]


@router.get("/sessions/{conversation_id}")
def history(request, conversation_id: str):
    who = request.identity
    conv = Conversation.objects.filter(pk=conversation_id, user_key=who.user_key).first()
    if conv is None:                     # 别人的会话按不存在处理，不暴露存在性
        return []
    return [
        {
            "turn": m.turn,
            "role": m.role,
            "content": m.content,
            "intent": m.intent,
            "answerable": m.answerable,
            "refusal_reason": m.refusal_reason,
            "latency_ms": m.latency_ms,
            "created_at": m.created_at,
            "payload": m.payload or {},
        }
        for m in Message.objects.filter(conversation=conv)
    ]


@router.post("/export")
def export(request, payload: ExportIn):
    """把勾选后的清单导成 CSV。

    导出的是**前端当前的勾选状态**，不是后端数据——所以由前端把条目带上来，
    后端只负责排版与编码。CSV 带 UTF-8 BOM，Excel 双击不乱码。
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["序号", "类型", "内容", "是否已备"])
    kinds = {"material": "材料", "step": "步骤", "condition": "条件", "notice": "提示"}
    for i, item in enumerate(payload.items, 1):
        mark = "√" if item.checked else ""
        writer.writerow([i, kinds.get(item.kind, item.kind), item.text, mark])
    body = "\ufeff" + buffer.getvalue()

    stamp = datetime.now().strftime("%Y%m%d%H%M")
    filename = f"{payload.title}-{stamp}.csv"
    response = HttpResponse(body, content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = (
        f"attachment; filename=\"checklist-{stamp}.csv\"; "
        f"filename*=UTF-8''{_quote(filename)}"
    )
    return response


def _quote(name: str) -> str:
    from urllib.parse import quote

    return quote(name, safe="")
