"""数据库 / Redis / 对象存储三项探活。

口径：只判断“能不能用”，异常一律吞掉转成 ok=false + 具体原因，不把栈抛给调用方。
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx
from django.conf import settings
from django.core.cache import cache
from django.db import connection

PROBE_KEY = "_probe"
PROBE_TTL = 10
STORAGE_TIMEOUT = 2.0


@dataclass(frozen=True)
class CheckResult:
    ok: bool
    detail: str


def check_db() -> CheckResult:
    """查 PG 版本与 pgvector 扩展版本。扩展缺失判 false。"""
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT version()")
            row = cur.fetchone()
            pg_version = (row[0] if row else "").split(" on ")[0].replace("PostgreSQL ", "pg ")

            cur.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
            ext = cur.fetchone()

        if not ext:
            return CheckResult(False, f"{pg_version} / vector extension missing")
        return CheckResult(True, f"{pg_version} / vector {ext[0]}")
    except Exception as exc:  # 探活不抛栈
        return CheckResult(False, f"{type(exc).__name__}: {exc}")


def check_redis() -> CheckResult:
    """写一个短 TTL 探针再读回，验证读写通链路。"""
    try:
        cache.set(PROBE_KEY, 1, PROBE_TTL)
        if cache.get(PROBE_KEY) != 1:
            return CheckResult(False, "readback mismatch")
        return CheckResult(True, "read/write ok")
    except Exception as exc:  # 失败时只给异常类型，不回栈
        return CheckResult(False, type(exc).__name__)


def check_storage() -> CheckResult:
    """只探 MinIO 端点存活，不校验桶权限（桶由 minio-init 保证）。"""
    url = settings.MINIO_ENDPOINT.rstrip("/") + "/minio/health/live"
    try:
        # trust_env=False：探的是本机容器，不能走系统 HTTP_PROXY
        resp = httpx.get(url, timeout=STORAGE_TIMEOUT, trust_env=False)
        if resp.status_code == 200:
            return CheckResult(True, settings.MINIO_ENDPOINT)
        return CheckResult(False, f"HTTP {resp.status_code}")
    except Exception as exc:
        return CheckResult(False, f"{type(exc).__name__}: {exc}")
