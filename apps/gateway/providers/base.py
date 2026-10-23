"""适配器公共部分：连接池、并发闸门、超时、故障注入、错误归一。

子类只负责"拼请求体 / 解析响应"，其余都在这里。这样换协议族时异常口径不会走样。
"""

from __future__ import annotations

import asyncio

import httpx
from django.conf import settings
from django.core.cache import cache

from apps.gateway.base import (
    ContentBlocked,
    UpstreamBadRequest,
    UpstreamRateLimited,
    UpstreamServerError,
    UpstreamTimeout,
)

_clients: dict[int, tuple[asyncio.AbstractEventLoop, httpx.AsyncClient]] = {}
_sems: dict[int, tuple[asyncio.AbstractEventLoop, asyncio.Semaphore]] = {}

BLOCK_KEYWORDS = ("content_filter", "content policy", "sensitive", "safety", "审核", "违规")


def get_client() -> httpx.AsyncClient:
    """按 event loop 缓存客户端。

    httpx 的连接与创建的 loop 绑定：management command 每次 asyncio.run 都是新 loop，
    复用旧客户端会在关闭时炸 'Event loop is closed'。所以按 loop 分桶，
    loop 换了就重建，旧的自然被回收。也不在模块导入时创建（那时还没有 loop）。
    """
    loop = asyncio.get_running_loop()
    entry = _clients.get(id(loop))
    if entry is not None and entry[0] is loop:
        return entry[1]

    client = httpx.AsyncClient(
        # 位置参数是默认超时，connect 单列：read 与 connect 该给的额度差一个数量级
        timeout=httpx.Timeout(settings.GW_TIMEOUT_CHAT, connect=settings.GW_TIMEOUT_CONNECT),
        limits=httpx.Limits(max_connections=32, max_keepalive_connections=16),
        # 本机 HTTP_PROXY 不能把模型请求也转出去（与 P0 探活同理）
        trust_env=False,
    )
    _clients[id(loop)] = (loop, client)
    return client


def sem(slot: str) -> asyncio.Semaphore:
    """限并发。Semaphore 在 3.10 绑 event loop，按 loop 分桶，不能用一个全局变量。"""
    del slot
    loop = asyncio.get_running_loop()
    entry = _sems.get(id(loop))
    if entry is None or entry[0] is not loop:
        _sems[id(loop)] = (loop, asyncio.Semaphore(settings.GW_MAX_CONCURRENCY))
    return _sems[id(loop)][1]


def reset_pool() -> None:
    """丢弃已缓存的客户端与闸门。改配置后或测试隔离时用。"""
    _clients.clear()
    _sems.clear()


class BaseAdapter:
    task: str = "chat"
    slot: str = ""
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    timeout_read: float = 60.0

    # ------------------------------------------------------------ 内部工具

    def _url(self, path: str) -> str:
        return f"{self.base_url.rstrip('/')}{path}"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def _maybe_fault(self) -> None:
        """故障注入开关。总开关关闭时整段跳过，正常路径零额外开销。"""
        if not settings.GW_FAULT_INJECTION:
            return
        spec = cache.get(f"gw:fault:{self.slot}")
        if not spec or not isinstance(spec, dict):
            return
        mode = spec.get("mode")
        if mode == "timeout":
            raise UpstreamTimeout(f"fault-injected timeout on {self.slot}")
        if mode == "error500":
            raise UpstreamServerError(f"fault-injected 500 on {self.slot}", status=500)
        if mode == "ratelimit":
            raise UpstreamRateLimited(f"fault-injected 429 on {self.slot}", retry_after=2)
        if mode == "badjson":
            raise UpstreamBadRequest(f"fault-injected bad json on {self.slot}")
        if mode == "slow":
            await asyncio.sleep(5)

    def _normalize(self, resp: httpx.Response) -> None:
        """把各家错误体压成统一异常。错误体不原样上抛，避免 key 片段进日志。"""
        if resp.status_code < 300:
            return
        body = resp.text[:500]
        if resp.status_code == 429:
            raw = resp.headers.get("Retry-After")
            retry_after = float(raw) if raw and raw.replace(".", "", 1).isdigit() else None
            raise UpstreamRateLimited(f"429 {body}", retry_after=retry_after)
        if resp.status_code >= 500:
            raise UpstreamServerError(f"{resp.status_code} {body}", status=resp.status_code)
        lowered = body.lower()
        if any(k in lowered for k in BLOCK_KEYWORDS):
            raise ContentBlocked(body)
        raise UpstreamBadRequest(f"{resp.status_code} {body}", status=resp.status_code)

    # ------------------------------------------------------------ 发送

    async def post_json(self, path: str, body: dict, *, timeout: float | None = None) -> dict:
        await self._maybe_fault()
        url = self._url(path)
        try:
            async with sem(self.slot):
                resp = await get_client().post(
                    url,
                    json=body,
                    headers=self._headers(),
                    timeout=httpx.Timeout(
                        timeout or self.timeout_read,
                        connect=settings.GW_TIMEOUT_CONNECT,
                    ),
                )
        except httpx.TimeoutException as exc:
            raise UpstreamTimeout(f"{self.slot} 超时: {exc}") from exc
        except httpx.HTTPError as exc:  # 连接失败、DNS、协议错误一律按可重试处理
            raise UpstreamTimeout(f"{self.slot} 连接失败: {exc}") from exc

        self._normalize(resp)
        try:
            return resp.json()
        except ValueError as exc:
            raise UpstreamBadRequest(f"{self.slot} 响应不是合法 JSON") from exc

    async def iter_sse(self, path: str, body: dict, *, timeout: float | None = None):
        """逐行吐出 SSE 数据行。首包之前的异常可直接重试；调用方负责后续语义。"""
        await self._maybe_fault()
        url = self._url(path)
        try:
            async with sem(self.slot):
                async with get_client().stream(
                    "POST",
                    url,
                    json=body,
                    headers=self._headers(),
                    timeout=httpx.Timeout(
                        timeout or settings.GW_TIMEOUT_STREAM,
                        connect=settings.GW_TIMEOUT_CONNECT,
                    ),
                ) as resp:
                    if resp.status_code >= 300:
                        await resp.aread()
                        self._normalize(resp)
                    async for line in resp.aiter_lines():
                        yield line
        except httpx.TimeoutException as exc:
            raise UpstreamTimeout(f"{self.slot} 流式超时: {exc}") from exc
        except httpx.HTTPError as exc:
            raise UpstreamTimeout(f"{self.slot} 流式连接失败: {exc}") from exc


def parse_sse_data(line: str) -> str | None:
    """取 SSE 的 data 段。返回 None 表示该行不是数据行（空行 / 注释 / event:）。"""
    if not line or line.startswith(":"):
        return None
    if not line.startswith("data:"):
        return None
    return line[5:].strip()
