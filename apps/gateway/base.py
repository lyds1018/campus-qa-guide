"""模型网关的对外类型、异常树与适配器协议。

P3 只依赖 apps.gateway.gateway 与本模块，不感知 providers / router 的存在。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Literal, Protocol

# --------------------------------------------------------------- 异常树


class GatewayError(Exception):
    """网关异常基类。P3 catch 它就能兜住全部模型侧问题。"""


class UpstreamTimeout(GatewayError):
    """连接或读超时。"""


class UpstreamRateLimited(GatewayError):
    """429。retry_after 为供应商给的等待秒数，可能为空。"""

    def __init__(self, message: str = "rate limited", retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class UpstreamServerError(GatewayError):
    """5xx，或熔断打开时的快速失败。"""

    def __init__(self, message: str = "upstream 5xx", status: int = 500):
        super().__init__(message)
        self.status = status


class UpstreamBadRequest(GatewayError):
    """4xx，重试无意义。401/403 还会附带 key 配置错误的排查提示。"""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


class ContentBlocked(GatewayError):
    """触发供应商内容审核（finish_reason=content_filter）。"""


class StreamInterrupted(GatewayError):
    """已输出部分内容后断流。不重试，由 P4 决定怎么提示。"""


class DimensionMismatch(GatewayError):
    """向量维度与 settings.EMBEDDING_DIM 不一致，入库前必须拦住。"""


class NotConfigured(GatewayError):
    """该槽位未配置（embedding / rerank 允许空缺）。"""


class AllProvidersFailed(GatewayError):
    """整条降级链都失败。errors 是 [(槽位名, 异常类名), ...]。"""

    def __init__(self, task: str, errors: list[tuple[str, str]]):
        self.task = task
        self.errors = errors
        detail = "; ".join(f"{name}:{kind}" for name, kind in errors) or "未配置任何供应商"
        super().__init__(f"{task} 调用失败（{detail}）")


# --------------------------------------------------------------- 数据类型


@dataclass(frozen=True)
class ChatMessage:
    role: Literal["system", "user", "assistant"]
    content: str

    def as_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass(frozen=True)
class ChatParams:
    """白名单。调用方多传的键直接丢弃，不静默透传给供应商。"""

    temperature: float = 0.3
    top_p: float = 1.0
    max_tokens: int | None = None
    stop: list[str] = field(default_factory=list)
    seed: int | None = None
    json_mode: bool = False

    def as_payload(self) -> dict:
        body: dict = {"temperature": self.temperature}
        if self.top_p != 1.0:
            body["top_p"] = self.top_p
        if self.max_tokens:
            body["max_tokens"] = self.max_tokens
        if self.stop:
            body["stop"] = self.stop
        if self.seed is not None:
            body["seed"] = self.seed
        if self.json_mode:
            body["response_format"] = {"type": "json_object"}
        return body

    def cacheable(self) -> bool:
        """温度高的采样不缓存：缓存等于把随机性抹成确定性。"""
        return self.temperature <= 0.3


@dataclass(frozen=True)
class ChatResult:
    text: str
    model: str
    provider: str  # 槽位名：main / fallback / aux
    finish_reason: str
    prompt_tokens: int
    completion_tokens: int
    degraded: bool
    trace_id: str
    cached: bool = False


@dataclass(frozen=True)
class ChatDelta:
    text: str
    finish_reason: str | None = None


@dataclass(frozen=True)
class RankedDoc:
    index: int
    score: float


@dataclass(frozen=True)
class EmbedResult:
    vectors: list[list[float]]
    model: str
    prompt_tokens: int


# --------------------------------------------------------------- 适配器协议


class ChatAdapter(Protocol):
    slot: str
    model: str

    async def chat(self, messages: list[ChatMessage], params: ChatParams) -> ChatResult: ...

    def stream(
        self, messages: list[ChatMessage], params: ChatParams
    ) -> AsyncIterator[ChatDelta]: ...


class EmbedAdapter(Protocol):
    slot: str
    model: str

    async def embed(self, texts: list[str], kind: str) -> EmbedResult: ...


class RerankAdapter(Protocol):
    slot: str
    model: str

    async def rerank(self, query: str, docs: list[str], top_k: int) -> list[RankedDoc]: ...
