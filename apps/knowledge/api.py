"""知识库运维接口：只读统计与任务列表。导入走命令行，不开放上传面。"""

from __future__ import annotations

from datetime import datetime

from ninja import Router, Schema

from apps.knowledge.repositories import ReadRepository

router = Router(tags=["kb"])
_repo = ReadRepository()


class KbStats(Schema):
    documents: int
    documents_published: int
    chunks: int
    chunks_published: int
    chunks_embedded: int
    matters: int
    flows: int
    terms: int
    jobs_failed: int


class JobOut(Schema):
    id: int
    source_path: str
    status: str
    stage: str
    message: str
    created_at: datetime


@router.get("/stats", response=KbStats)
def stats(request):
    return _repo.stats()


@router.get("/jobs", response=list[JobOut])
def jobs(request, status: str | None = None, limit: int = 20):
    return [
        JobOut(
            id=j.pk,
            source_path=j.source_path,
            status=j.status,
            stage=j.stage,
            message=j.message,
            created_at=j.created_at,
        )
        for j in _repo.jobs(status=status, limit=min(limit, 100))
    ]
