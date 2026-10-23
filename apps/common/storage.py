"""MinIO 对象读写。

key 一律由服务端按规则生成，不接受调用方传入路径，避免穿越。
桶名取 MINIO_BUCKET（P0 由 minio-init 建好），P1 不负责建桶。
"""

from __future__ import annotations

import io
import json
from functools import lru_cache
from typing import Any

from django.conf import settings
from minio import Minio
from minio.error import S3Error


def _bucket() -> str:
    return settings.MINIO_BUCKET


@lru_cache(maxsize=1)
def _client() -> Minio:
    endpoint = settings.MINIO_ENDPOINT
    secure = endpoint.startswith("https://")
    host = endpoint.split("://", 1)[-1].rstrip("/")
    return Minio(
        host,
        access_key=settings.MINIO_ACCESS_KEY,
        secret_key=settings.MINIO_SECRET_KEY,
        secure=secure,
    )


def raw_key(checksum: str, ext: str, doc_type: str) -> str:
    """raw/{doc_type}/{sha[:2]}/{sha}.{ext}"""
    return f"raw/{doc_type}/{checksum[:2]}/{checksum}{ext}"


def parsed_key(document_id: int, version: int) -> str:
    """parsed/{document_id}/v{version}.json"""
    return f"parsed/{document_id}/v{version}.json"


def exists(key: str) -> bool:
    try:
        _client().stat_object(_bucket(), key)
        return True
    except S3Error:
        return False


def put_raw(checksum: str, ext: str, doc_type: str, data: bytes) -> str:
    key = raw_key(checksum, ext, doc_type)
    _client().put_object(
        _bucket(),
        key,
        io.BytesIO(data),
        length=len(data),
        content_type="application/octet-stream",
    )
    return key


def get_raw(key: str) -> bytes:
    resp = _client().get_object(_bucket(), key)
    try:
        return resp.read()
    finally:
        resp.close()
        resp.release_conn()


def put_parsed(document_id: int, version: int, payload: dict[str, Any]) -> str:
    key = parsed_key(document_id, version)
    data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    _client().put_object(
        _bucket(),
        key,
        io.BytesIO(data),
        length=len(data),
        content_type="application/json",
    )
    return key


def get_parsed(document_id: int, version: int) -> dict[str, Any]:
    resp = _client().get_object(_bucket(), parsed_key(document_id, version))
    try:
        return json.loads(resp.read().decode("utf-8"))
    finally:
        resp.close()
        resp.release_conn()
