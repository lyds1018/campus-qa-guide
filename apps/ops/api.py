"""运营接口（M2 的服务端）。全部走 `/api/ops`，中间件已限定管理员 token。

六组：上传与任务、审核与版本、文档与向量、事项、词典、模型槽位，外加一个看板。
"""

from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timedelta
from pathlib import Path

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.db.models import Count
from django.utils import timezone
from ninja import File, Form, Router, Schema
from ninja.errors import HttpError
from ninja.files import UploadedFile

from apps.gateway import overrides
from apps.gateway.base import GatewayError
from apps.gateway.gateway import gateway
from apps.gateway.models import ModelSetting
from apps.knowledge import queue
from apps.knowledge.models import (
    Chunk,
    DocType,
    Document,
    Flow,
    IngestJob,
    JobStatus,
    Matter,
    PublishStatus,
    Term,
)
from apps.knowledge.parsing import SUPPORTED_SUFFIXES
from apps.knowledge.repositories import ReadRepository, WriteRepository
from apps.ops import conflict
from apps.orchestrator.models import Message

router = Router(tags=["ops"])
# 放在模块级：函数默认值里直接调 File() 会被 lint 判为"调用在默认值里"（B008）
UPLOAD_FILE = File(...)
repo = ReadRepository()
writer = WriteRepository()


# --------------------------------------------------------------- 上传与任务
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


@router.post("/uploads", response=UploadOut)
def upload(
    request,
    file: UploadedFile = UPLOAD_FILE,
    doc_type: str = Form("guide"),
    dept: str = Form(""),
):
    """存原件 → 建任务 → 入队。解析与切分仍由 P1 的 worker 做，这里不重复实现。"""
    suffix = Path(file.name or "").suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise HttpError(400, f"不支持的文件类型：{suffix or '(无扩展名)'}")
    if doc_type not in DocType.values:
        raise HttpError(400, f"未知文档类型：{doc_type}")

    data = file.read()
    limit = settings.OPS_UPLOAD_MAX_MB * 1024 * 1024
    if len(data) > limit:
        raise HttpError(413, f"文件超过 {settings.OPS_UPLOAD_MAX_MB}MB")

    checksum = hashlib.sha256(data).hexdigest()
    existed = writer.find_by_checksum(checksum)
    if existed is not None:
        raise HttpError(409, f"该文件已存在：doc#{existed.pk}《{existed.title}》")

    # 按 checksum 分目录、保留原文件名：P1 的 guess_title 取的是文件名主干，
    # 直接用 checksum 命名会把所有上传文档的标题都变成一串哈希
    safe_name = Path(file.name or f"upload{suffix}").name[:80]
    folder = Path(settings.OPS_UPLOAD_DIR) / checksum[:12]
    if folder.exists() and any(folder.iterdir()):
        # 原件还在暂存区：要么任务在排队，要么上次入库失败后没清理
        raise HttpError(409, "同内容文件已上传过（可能仍在队列中），请先看任务列表")
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / safe_name
    path.write_bytes(data)

    job = IngestJob.objects.create(
        source_path=str(path), doc_type=doc_type, dept=dept, publish=False
    )
    queue.push(job.pk)
    return UploadOut(
        job_id=job.pk,
        filename=file.name or path.name,
        size=len(data),
        doc_type=doc_type,
        checksum=checksum,
    )


@router.get("/jobs", response=list[JobOut])
def jobs(request, status: str | None = None, limit: int = 30):
    rows = repo.jobs(status=status, limit=min(limit, 100))
    return [
        JobOut(
            id=j.pk,
            source_path=Path(j.source_path).name,
            doc_type=j.doc_type,
            status=j.status,
            stage=j.stage,
            message=j.message,
            document_id=j.document_id,
            started_at=j.started_at,
            finished_at=j.finished_at,
            created_at=j.created_at,
        )
        for j in rows
    ]


@router.post("/jobs/{job_id}/retry")
def retry_job(request, job_id: int):
    job = IngestJob.objects.filter(pk=job_id).first()
    if job is None:
        raise HttpError(404, "任务不存在")
    if job.status == JobStatus.RUNNING:
        raise HttpError(409, "任务正在执行，不能重试")
    job.status = JobStatus.PENDING
    job.stage = ""
    job.message = ""
    job.started_at = None
    job.finished_at = None
    job.save(update_fields=["status", "stage", "message", "started_at", "finished_at"])
    queue.push(job.pk)
    return {"job_id": job.pk, "status": job.status}


# --------------------------------------------------------------- 审核与版本
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


@router.get("/review", response=list[ReviewOut])
def review(request, limit: int = 30):
    docs = Document.objects.filter(status=PublishStatus.DRAFT).order_by("-created_at")[
        : min(limit, 100)
    ]
    out = []
    for doc in docs:
        chunks = Chunk.objects.filter(document=doc)
        out.append(
            ReviewOut(
                id=doc.pk,
                title=doc.title,
                doc_type=doc.doc_type,
                dept=doc.dept,
                version=doc.version,
                chunks=chunks.count(),
                embedded=chunks.exclude(embedding=None).count(),
                created_at=doc.created_at,
                conflicts=[ConflictOut(**c.as_dict()) for c in conflict.scan(doc)],
            )
        )
    return out


def _publish(doc: Document) -> None:
    """发布一份文档：同标题在版先归档，再发布它，最后让缓存失效。"""
    writer.archive_existing(doc.title, doc.doc_type)
    writer.publish(doc)
    _invalidate_kb()


def _invalidate_kb() -> None:
    # 知识换版必须让答案缓存与词典缓存立刻失效，否则 60s 内还在答旧口径
    cache.delete("gw:kb:fingerprint")
    cache.delete("qa:terms")


@router.post("/review/{doc_id}/publish")
def publish(request, doc_id: int):
    doc = Document.objects.filter(pk=doc_id).first()
    if doc is None:
        raise HttpError(404, "文档不存在")
    if doc.status == PublishStatus.PUBLISHED:
        raise HttpError(409, "该版本已是发布状态")
    _publish(doc)
    return {"id": doc.pk, "status": PublishStatus.PUBLISHED, "title": doc.title}


@router.post("/review/{doc_id}/archive")
def archive(request, doc_id: int):
    doc = Document.objects.filter(pk=doc_id).first()
    if doc is None:
        raise HttpError(404, "文档不存在")
    writer.archive(doc)
    _invalidate_kb()
    return {"id": doc.pk, "status": PublishStatus.ARCHIVED}


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


@router.get("/documents", response=list[DocOut])
def documents(request, query: str = "", status: str | None = None, limit: int = 50):
    qs = Document.objects.all()
    if query:
        qs = qs.filter(title__icontains=query)
    if status:
        qs = qs.filter(status=status)
    out = []
    for doc in qs.order_by("-created_at")[: min(limit, 200)]:
        chunks = Chunk.objects.filter(document=doc)
        out.append(
            DocOut(
                id=doc.pk,
                title=doc.title,
                doc_type=doc.doc_type,
                status=doc.status,
                version=doc.version,
                chunks=chunks.count(),
                embedded=chunks.exclude(embedding=None).count(),
                published_at=doc.published_at,
                created_at=doc.created_at,
            )
        )
    return out


@router.get("/documents/{doc_id}/versions", response=list[DocOut])
def versions(request, doc_id: int):
    doc = Document.objects.filter(pk=doc_id).first()
    if doc is None:
        raise HttpError(404, "文档不存在")
    return documents(request, query=doc.title, status=None, limit=50)


@router.post("/documents/{doc_id}/rollback")
def rollback(request, doc_id: int):
    """回滚 = 发布旧版本。旧版先被归档过，这里会重新发布并把当前版归档。"""
    target = Document.objects.filter(pk=doc_id).first()
    if target is None:
        raise HttpError(404, "文档不存在")
    if target.status == PublishStatus.PUBLISHED:
        raise HttpError(409, "该版本已是发布状态")
    _publish(target)
    return {"id": target.pk, "title": target.title, "version": target.version}


@router.post("/documents/{doc_id}/embed")
async def embed_document(request, doc_id: int):
    """给这份文档的块补向量。发布后不补，向量召回就找不到新内容。"""
    doc = await asyncio.to_thread(lambda: Document.objects.filter(pk=doc_id).first())
    if doc is None:
        raise HttpError(404, "文档不存在")

    ids = await asyncio.to_thread(
        lambda: list(
            Chunk.objects.filter(document=doc, embedding__isnull=True).values_list("id", flat=True)
        )
    )
    if not ids:
        return {"document_id": doc.pk, "filled": 0}

    filled = 0
    for start in range(0, len(ids), 32):
        batch_ids = ids[start : start + 32]
        rows = await asyncio.to_thread(
            lambda ids=batch_ids: list(Chunk.objects.filter(pk__in=ids))
        )
        try:
            vectors = await gateway.embed([c.content for c in rows], kind="doc")
        except GatewayError as exc:
            raise HttpError(503, f"向量服务不可用：{type(exc).__name__}") from exc
        for row, vec in zip(rows, vectors, strict=False):
            row.embedding = vec
        await asyncio.to_thread(Chunk.objects.bulk_update, rows, ["embedding"])
        filled += len(rows)
    return {"document_id": doc.pk, "filled": filled}


# --------------------------------------------------------------- 看板
@router.get("/dashboard")
def dashboard(request):
    day_ago = timezone.now() - timedelta(days=1)
    answers = Message.objects.filter(
        role=Message.Role.ASSISTANT, created_at__gte=day_ago
    )
    total = answers.count()
    refused = answers.filter(answerable=False).count()
    latencies = list(answers.values_list("latency_ms", flat=True))
    latencies.sort()

    def pct(value: float) -> float:
        return round(value * 100, 1)

    return {
        "documents": {
            "total": Document.objects.count(),
            "published": Document.objects.filter(status=PublishStatus.PUBLISHED).count(),
            "draft": Document.objects.filter(status=PublishStatus.DRAFT).count(),
            "archived": Document.objects.filter(status=PublishStatus.ARCHIVED).count(),
        },
        "chunks": {
            "total": Chunk.objects.count(),
            "published": Chunk.objects.filter(status=PublishStatus.PUBLISHED).count(),
            "embedded": Chunk.objects.exclude(embedding=None).count(),
        },
        "matters": Matter.objects.count(),
        "flows": Flow.objects.count(),
        "terms": Term.objects.count(),
        "jobs": {
            row["status"]: row["n"]
            for row in IngestJob.objects.values("status").annotate(n=Count("id"))
        },
        "queue_depth": queue.depth(),
        "qa_24h": {
            "turns": total,
            "refused": refused,
            "refusal_rate": pct(refused / total) if total else 0.0,
            "p50_ms": latencies[len(latencies) // 2] if latencies else 0,
            "p95_ms": latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))]
            if latencies
            else 0,
        },
    }


# --------------------------------------------------------------- 事项
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


@router.get("/matters", response=list[MatterOut])
def matters(request, query: str = ""):
    qs = Matter.objects.all()
    if query:
        qs = qs.filter(name__icontains=query)
    counts = dict(Flow.objects.values_list("matter_id").annotate(n=Count("id")))
    return [
        MatterOut(
            code=m.code,
            name=m.name,
            dept=m.dept,
            category=m.category,
            audience=m.audience,
            location=m.location,
            contact=m.contact,
            summary=m.summary,
            status=m.status,
            steps=counts.get(m.pk, 0),
        )
        for m in qs.order_by("code")[:200]
    ]


@router.post("/matters", response=MatterOut)
def upsert_matter(request, payload: MatterIn):
    code = payload.code or f"G{hashlib.sha1(payload.name.encode()).hexdigest()[:10].upper()}"
    matter = writer.upsert_matter(
        code,
        name=payload.name,
        dept=payload.dept,
        category=payload.category,
        audience=payload.audience,
        summary=payload.summary,
        location=payload.location,
        contact=payload.contact,
        status=payload.status,
    )
    return MatterOut(
        code=matter.code,
        name=matter.name,
        dept=matter.dept,
        category=matter.category,
        audience=matter.audience,
        location=matter.location,
        contact=matter.contact,
        summary=matter.summary,
        status=matter.status,
        steps=Flow.objects.filter(matter=matter).count(),
    )


# --------------------------------------------------------------- 词典
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


@router.get("/terms", response=list[TermOut])
def terms(request, query: str = "", limit: int = 100):
    qs = Term.objects.all()
    if query:
        qs = qs.filter(term__icontains=query) | qs.filter(canonical__icontains=query)
    return [
        TermOut(id=t.pk, term=t.term, canonical=t.canonical, term_type=t.term_type, weight=t.weight)
        for t in qs.order_by("term")[: min(limit, 300)]
    ]


@router.post("/terms")
def upsert_terms(request, rows: list[TermIn]):
    created = writer.upsert_terms([row.model_dump() for row in rows])
    cache.delete("qa:terms")           # 词典缓存必须立刻失效，否则改写还用旧词表
    return {"created": created, "total": len(rows)}


@router.delete("/terms/{term_id}")
def delete_term(request, term_id: int):
    deleted, _ = Term.objects.filter(pk=term_id).delete()
    cache.delete("qa:terms")
    return {"deleted": deleted}


# --------------------------------------------------------------- 模型槽位
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


def _slot_cfg() -> dict[str, tuple[str, str, bool]]:
    s = settings
    return {
        "main": (s.GW_CHAT_MAIN_BASE_URL, s.GW_CHAT_MAIN_MODEL, bool(s.GW_CHAT_MAIN_API_KEY)),
        "fallback": (
            s.GW_CHAT_FALLBACK_BASE_URL,
            s.GW_CHAT_FALLBACK_MODEL,
            bool(s.GW_CHAT_FALLBACK_API_KEY),
        ),
        "aux": (s.GW_CHAT_AUX_BASE_URL, s.GW_CHAT_AUX_MODEL, bool(s.GW_CHAT_AUX_API_KEY)),
        "embed": (s.GW_EMBED_BASE_URL, s.GW_EMBED_MODEL, bool(s.GW_EMBED_API_KEY)),
        "rerank": (s.GW_RERANK_BASE_URL, s.GW_RERANK_MODEL, bool(s.GW_RERANK_API_KEY)),
    }


@router.get("/models", response=list[ModelOut])
def models(request):
    rows = {row.slot: row for row in ModelSetting.objects.all()}
    out = []
    for slot, (base_url, model, has_key) in _slot_cfg().items():
        row = rows.get(slot)
        effective_url, effective_model = overrides.resolve(slot, base_url, model)
        out.append(
            ModelOut(
                slot=slot,
                base_url=effective_url,
                model=effective_model,
                has_key=has_key,
                overridden=bool(row and (row.base_url or row.model)),
                enabled=row.enabled if row else True,
                note=row.note if row else "",
            )
        )
    return out


@router.put("/models/{slot}", response=ModelOut)
def update_model(request, slot: str, payload: ModelIn):
    if slot not in ModelSetting.SLOTS:
        raise HttpError(400, f"未知槽位：{slot}")
    with transaction.atomic():
        ModelSetting.objects.update_or_create(
            slot=slot,
            defaults={
                "base_url": payload.base_url.strip(),
                "model": payload.model.strip(),
                "enabled": payload.enabled,
                "note": payload.note,
            },
        )
    overrides.invalidate()
    base_url, model, has_key = _slot_cfg()[slot]
    effective_url = payload.base_url.strip() or base_url
    effective_model = payload.model.strip() or model
    return ModelOut(
        slot=slot,
        base_url=effective_url,
        model=effective_model,
        has_key=has_key,
        overridden=bool(payload.base_url.strip() or payload.model.strip()),
        enabled=payload.enabled,
        note=payload.note,
    )
