"""M14 异步任务：Redis List 队列 + PG 任务表。

分工：
- ingest_jobs 是唯一事实源（状态、阶段、错误）；
- Redis 只排队 job_id，丢了可以从 PG 的 pending 重建；
- worker 启动时把超时未结束的 running 重置为 pending。

升级条件：出现多 worker 并发、定时任务、指数退避重试时换 RQ（同为 Redis）。
"""

from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from apps.knowledge.models import IngestJob, JobStatus


def _redis():
    return cache.client.get_client(write=True)


def push(job_id: int) -> None:
    _redis().lpush(settings.INGEST_QUEUE, job_id)


def pop(timeout: int = 5) -> int | None:
    item = _redis().brpop([settings.INGEST_QUEUE], timeout=timeout)
    if not item:
        return None
    return int(item[1])


def depth() -> int:
    return int(_redis().llen(settings.INGEST_QUEUE))


def reset_stale(minutes: int | None = None) -> int:
    """把长时间停留在 running 的任务重置为 pending（进程被杀的兜底）。"""
    minutes = settings.WORKER_STALE_MINUTES if minutes is None else minutes
    cutoff = timezone.now() - timedelta(minutes=minutes)
    return IngestJob.objects.filter(
        status=JobStatus.RUNNING, started_at__lt=cutoff
    ).update(status=JobStatus.PENDING, started_at=None, message="重置僵尸任务")


def requeue_pending() -> int:
    """PG 里 pending 但队列可能已丢的任务重新入队。"""
    ids = list(
        IngestJob.objects.filter(status=JobStatus.PENDING)
        .order_by("id")
        .values_list("id", flat=True)
    )
    for job_id in ids:
        push(job_id)
    return len(ids)


def process_job(job_id: int) -> str:
    """执行一条任务，返回最终状态。异常一律落到 failed，不抛出。"""
    from apps.knowledge.ingest import process_file
    from apps.knowledge.repositories import WriteRepository

    job = IngestJob.objects.filter(pk=job_id).first()
    if job is None:
        return "missing"
    if job.status != JobStatus.PENDING:
        return job.status

    job.status = JobStatus.RUNNING
    job.started_at = timezone.now()
    job.message = ""
    job.save(update_fields=["status", "started_at", "message"])

    def on_stage(name: str) -> None:
        job.stage = name
        job.save(update_fields=["stage"])

    from pathlib import Path

    try:
        status, doc, msg, _n = process_file(
            Path(job.source_path),
            doc_type=job.doc_type,
            dept=job.dept,
            publish=job.publish,
            repo=WriteRepository(),
            rel_path=job.source_path,
            on_stage=on_stage,
        )
    except Exception as exc:
        status, doc, msg = JobStatus.FAILED, None, f"{type(exc).__name__}: {exc}"

    job.status = status
    job.document = doc
    job.message = msg
    job.finished_at = timezone.now()
    job.save(update_fields=["status", "document", "message", "finished_at"])
    return status
