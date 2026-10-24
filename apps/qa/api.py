"""问答接口：一问一答的 JSON 形态。

只给联调、排障与离线评测用。正式流式出口由编排器提供 SSE 帧、心跳与断线重连，
这里保持简单的一问一答 JSON 协议。
"""

from __future__ import annotations

from ninja import Router, Schema

from apps.qa.pipeline import qa

router = Router(tags=["qa"])


class AskIn(Schema):
    question: str
    audience: str = "unknown"
    doc_types: list[str] | None = None


@router.post("/ask")
async def ask(request, payload: AskIn):
    answer = await qa.answer(
        payload.question, audience=payload.audience, doc_types=payload.doc_types
    )
    return answer.as_dict()
