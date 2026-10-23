"""问答接口：一问一答的 JSON 形态。

只给联调、命令行以外的排障与 P7 评测用。正式的流式出口（SSE 帧、心跳、断线重连）
是 P5 的职责，这里不提前实现。
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
