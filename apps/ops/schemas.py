"""运营接口的请求/响应模型。

放在独立模块，让 `api.py` 只保留路由与编排；这些模型同时是 Ninja OpenAPI
和前端的契约，不应被业务实现淹没。
"""

from __future__ import annotations

from datetime import datetime

from ninja import Schema

from apps.knowledge.models import PublishStatus


class UploadOut(Schema):
    job_id: int
    filename: str
    size: int
    doc_type: str
    checksum: str


class JobOut(Schema):
    id: int
    source_path: str
    doc_type: str
    status: str
    stage: str
    message: str
    document_id: int | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime


class ConflictOut(Schema):
    field: str
    draft: str
    published: str
    published_doc: str
    published_doc_id: int


class ReviewOut(Schema):
    id: int
    title: str
    doc_type: str
    dept: str
    version: int
    chunks: int
    embedded: int
    created_at: datetime
    conflicts: list[ConflictOut]


class DocOut(Schema):
    id: int
    title: str
    doc_type: str
    status: str
    version: int
    chunks: int
    embedded: int
    published_at: datetime | None = None
    created_at: datetime


class MatterIn(Schema):
    code: str | None = None
    name: str
    dept: str = ""
    category: str = ""
    audience: str = ""
    summary: str = ""
    location: str = ""
    contact: str = ""
    status: str = PublishStatus.PUBLISHED


class MatterOut(Schema):
    code: str
    name: str
    dept: str
    category: str
    audience: str
    location: str
    contact: str
    summary: str
    status: str
    steps: int


class TermIn(Schema):
    term: str
    canonical: str
    term_type: str = "alias"
    weight: int = 1


class TermOut(Schema):
    id: int
    term: str
    canonical: str
    term_type: str
    weight: int


class ModelOut(Schema):
    slot: str
    base_url: str
    model: str
    has_key: bool
    overridden: bool
    enabled: bool
    note: str


class ModelIn(Schema):
    base_url: str = ""
    model: str = ""
    enabled: bool = True
    note: str = ""
