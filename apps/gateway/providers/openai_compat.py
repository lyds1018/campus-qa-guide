"""OpenAI 兼容协议适配器：chat（含流式）+ embedding。

DeepSeek / 百炼 / 火山 / 硅基流动 / 自建 vLLM 都用这套字段，换厂只改 .env。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from django.conf import settings

from apps.gateway.base import (
    ChatDelta,
    ChatMessage,
    ChatParams,
    ChatResult,
    ContentBlocked,
    EmbedResult,
    UpstreamBadRequest,
)
from apps.gateway.providers.base import BaseAdapter, parse_sse_data

CHAT_PATH = "/chat/completions"
EMBED_PATH = "/embeddings"


class OpenAICompatAdapter(BaseAdapter):
    task = "chat"
    timeout_read = 60.0

    def __init__(
        self,
        *,
        slot: str,
        base_url: str,
        api_key: str,
        model: str,
        doc_prefix: str = "",
        query_prefix: str = "",
    ):
        self.slot = slot
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.doc_prefix = doc_prefix
        self.query_prefix = query_prefix

    # ------------------------------------------------------------ chat

    def _chat_body(
        self, messages: list[ChatMessage], params: ChatParams, stream: bool
    ) -> dict:
        body = {
            "model": self.model,
            "messages": [m.as_dict() for m in messages],
            **params.as_payload(),
        }
        if stream:
            body["stream"] = True
            body["stream_options"] = {"include_usage": True}
        return body

    async def chat(self, messages: list[ChatMessage], params: ChatParams) -> ChatResult:
        if not messages:
            raise UpstreamBadRequest("messages 不能为空")
        data = await self.post_json(
            CHAT_PATH, self._chat_body(messages, params, False), timeout=settings.GW_TIMEOUT_CHAT
        )

        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise UpstreamBadRequest(f"{self.slot} 响应缺少 choices")
        choice = choices[0]
        finish_reason = choice.get("finish_reason") or "stop"
        if finish_reason == "content_filter":
            raise ContentBlocked(f"{self.slot} 触发内容审核")

        usage = data.get("usage") or {}
        return ChatResult(
            text=((choice.get("message") or {}).get("content") or "").strip(),
            model=data.get("model") or self.model,
            provider=self.slot,
            finish_reason=finish_reason,
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
            degraded=False,
            trace_id="",
        )

    async def stream(
        self,
        messages: list[ChatMessage],
        params: ChatParams,
        usage: dict | None = None,
    ) -> AsyncIterator[ChatDelta]:
        if not messages:
            raise UpstreamBadRequest("messages 不能为空")
        body = self._chat_body(messages, params, True)
        model_name = self.model

        async for line in self.iter_sse(CHAT_PATH, body, timeout=settings.GW_TIMEOUT_STREAM):
            payload = parse_sse_data(line)
            if payload is None:
                continue
            if payload == "[DONE]":
                return
            try:
                chunk = json.loads(payload)
            except json.JSONDecodeError:
                continue  # 单行坏包不中断整段

            model_name = chunk.get("model") or model_name
            if chunk.get("usage") and usage is not None:
                usage.update(
                    {
                        "prompt_tokens": int(chunk["usage"].get("prompt_tokens") or 0),
                        "completion_tokens": int(
                            chunk["usage"].get("completion_tokens") or 0
                        ),
                        "model": model_name,
                    }
                )
            for choice in chunk.get("choices") or []:
                delta = choice.get("delta") or {}
                text = delta.get("content") or ""
                finish = choice.get("finish_reason")
                if text or finish:
                    yield ChatDelta(text=text, finish_reason=finish)

    # ------------------------------------------------------------ embedding

    async def embed(self, texts: list[str], kind: str = "doc") -> EmbedResult:
        if not texts:
            return EmbedResult(vectors=[], model=self.model, prompt_tokens=0)
        prefix = self.query_prefix if kind == "query" else self.doc_prefix
        payload = [f"{prefix}{t}" for t in texts] if prefix else list(texts)

        data = await self.post_json(
            EMBED_PATH,
            {"model": self.model, "input": payload},
            timeout=settings.GW_TIMEOUT_EMBED,
        )
        items = data.get("data")
        if not isinstance(items, list) or len(items) != len(texts):
            raise UpstreamBadRequest(
                f"{self.slot} embedding 返回 {len(items or [])} 条，期望 {len(texts)} 条"
            )

        # 供应商不保证顺序，必须按 index 归位，否则向量会绑到错的块上且完全静默
        slots: list[list[float] | None] = [None] * len(texts)
        for item in items:
            idx = item.get("index")
            vec = item.get("embedding")
            if not isinstance(idx, int) or not (0 <= idx < len(texts)) or vec is None:
                raise UpstreamBadRequest(f"{self.slot} embedding 返回结构异常")
            slots[idx] = [float(x) for x in vec]

        if any(v is None for v in slots):
            raise UpstreamBadRequest(f"{self.slot} embedding 返回 index 不完整")
        usage = data.get("usage") or {}
        return EmbedResult(
            vectors=[v or [] for v in slots],
            model=data.get("model") or self.model,
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
        )
