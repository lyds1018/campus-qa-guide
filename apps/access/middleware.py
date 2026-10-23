"""三个中间件：追踪、身份与限流、审计。

顺序（Django 按 MIDDLEWARE 列表从上到下进、从下到上出）：

    TraceId  →  Audit  →  Access  →  [视图]

- TraceId 最先：后面所有日志与 `ai_calls` 都要这个 id；
- Audit 在 Access 外层：401/403/429 也要留痕，否则"谁在被限流"查不到；
  Audit 的写库发生在内层响应之后，此时 `request.identity` 已被 Access 填好；
- Access 最靠近视图：限流计数只在该拦的地方拦，别把限流花在静态文件上。
"""

from __future__ import annotations

import logging
import time
import uuid

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse

from apps.access import identity, limit

logger = logging.getLogger(__name__)

# 不需要身份的路径：健康检查给探活用，文档页只在 DEBUG 下有意义
OPEN_PATHS = ("/api/health", "/api/docs", "/api/openapi.json")
ADMIN_PREFIX = "/api/ops"


class TraceIdMiddleware:
    """透传或生成 X-Trace-Id。前端带了就复用，方便一次操作串起整条链路。"""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        incoming = (request.headers.get("X-Trace-Id") or "").strip()
        request.trace_id = incoming or str(uuid.uuid4())
        request.started_at = time.monotonic()
        response = self.get_response(request)
        response["X-Trace-Id"] = request.trace_id
        return response


class AccessMiddleware:
    """身份 + 限流 + 角色门槛。

    只在 `/api/` 生效：静态文件、Django admin 后台走自己的认证，不在这里重复管。
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        path = request.path
        request.identity = None
        request.rate_bucket = ""

        if not path.startswith("/api/") or path.startswith(OPEN_PATHS):
            return self.get_response(request)

        who = identity.resolve(request)
        if who is None:
            return _json(401, "缺少或无效的 X-Demo-Token，请先登录")
        if path.startswith(ADMIN_PREFIX) and not who.is_admin:
            return _json(403, "该接口仅管理员可用")

        bucket = limit.bucket_of(request.method, path)
        allowed, remaining = limit.hit(bucket, who.user_key)
        request.rate_bucket = bucket
        if not allowed:
            response = _json(429, "请求过于频繁，请稍后再试")
            response["Retry-After"] = str(limit.retry_after())
            response["X-RateLimit-Remaining"] = "0"
            return response

        request.identity = who
        response = self.get_response(request)
        response["X-RateLimit-Remaining"] = str(remaining)
        return response


class AuditMiddleware:
    """一行一次请求。写库失败只记日志——审计不是事实源，不能把接口搞挂。"""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self.get_response(request)
        if not settings.ACCESS_AUDIT_ENABLED or not request.path.startswith("/api/"):
            return response
        if request.path.startswith(OPEN_PATHS):
            return response
        try:
            self._write(request, response)
        except Exception:  # noqa: BLE001
            logger.warning("审计落库失败 path=%s", request.path, exc_info=True)
        return response

    def _write(self, request: HttpRequest, response: HttpResponse) -> None:
        from apps.access.models import ApiLog

        who = getattr(request, "identity", None)
        started = getattr(request, "started_at", None)
        status = response.status_code
        ApiLog.objects.create(
            trace_id=getattr(request, "trace_id", ""),
            user_key=who.user_key if who else "",
            role=who.role if who else "",
            method=request.method or "",
            path=request.path[:200],
            status=status,
            latency_ms=int((time.monotonic() - started) * 1000) if started else 0,
            ip=_client_ip(request),
            bucket=getattr(request, "rate_bucket", ""),
            limited=status == 429,
            error="" if status < 400 else response.get("X-Error", "")[:200],
        )


def _client_ip(request: HttpRequest) -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    return (request.META.get("REMOTE_ADDR") or "")[:64]


def _json(status: int, detail: str) -> JsonResponse:
    return JsonResponse({"detail": detail}, status=status)
