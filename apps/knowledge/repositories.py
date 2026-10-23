"""四库仓储层。

M10（只读）与 M11（写入）在代码层分开：
- ReadRepository 只暴露查询，且只返回 published 且在时效内的数据；
- WriteRepository 继承它再加写方法。
L4 侧（P3 之后）只允许 import ReadRepository，直接写表即破坏"唯一可信事实源"。
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from typing import Any

from django.db import transaction
from django.db.models import Count, Q, QuerySet
from django.utils import timezone

from apps.knowledge.models import (
    Chunk,
    Document,
    Flow,
    IngestJob,
    JobStatus,
    Matter,
    PublishStatus,
    Term,
)


def _effective_q(today: date | None = None, prefix: str = "") -> Q:
    """未过期：effective_to 为空或 >= 今天。prefix 用于跨表查询（document__）。"""
    today = today or timezone.localdate()
    return Q(**{f"{prefix}effective_to__isnull": True}) | Q(
        **{f"{prefix}effective_to__gte": today}
    )


class ReadRepository:
    """只读视图。所有方法都不会修改数据。"""

    def documents(self, doc_type: str | None = None) -> QuerySet[Document]:
        qs = Document.objects.filter(status=PublishStatus.PUBLISHED)
        if doc_type:
            qs = qs.filter(doc_type=doc_type)
        return qs

    def document(self, document_id: int) -> Document | None:
        return self.documents().filter(pk=document_id).first()

    def chunks_of(self, document_id: int) -> QuerySet[Chunk]:
        return Chunk.objects.filter(
            document_id=document_id, status=PublishStatus.PUBLISHED
        ).order_by("ordinal")

    def active_chunks(self, doc_types: Iterable[str] | None = None) -> QuerySet[Chunk]:
        """供 P3 召回用：已发布且在时效内的块。"""
        qs = Chunk.objects.filter(
            status=PublishStatus.PUBLISHED,
            document__status=PublishStatus.PUBLISHED,
        ).filter(_effective_q(prefix="document__"))
        if doc_types:
            qs = qs.filter(document__doc_type__in=list(doc_types))
        return qs

    def chunk(self, chunk_id: int) -> Chunk | None:
        return self.active_chunks().filter(pk=chunk_id).first()

    def matters(self) -> QuerySet[Matter]:
        return Matter.objects.filter(status=PublishStatus.PUBLISHED).filter(_effective_q())

    def matter_by_code(self, code: str) -> Matter | None:
        return self.matters().filter(code=code).first()

    def flows_of(self, matter: Matter) -> QuerySet[Flow]:
        return Flow.objects.filter(matter=matter).order_by("step_no")

    def resolve_term(self, text: str) -> str | None:
        """精确命中别名时返回规范名，供 M5 改写用。"""
        row = Term.objects.filter(term=text).order_by("-weight").first()
        return row.canonical if row else None

    def terms_map(self) -> dict[str, str]:
        """全部别名 → 规范名。weight 大的优先，供 M5 做一次性批量改写。"""
        out: dict[str, str] = {}
        for term, canonical in Term.objects.order_by("-weight").values_list(
            "term", "canonical"
        ):
            out.setdefault(term, canonical)
        return out

    def stats(self) -> dict[str, int]:
        published_docs = Document.objects.filter(status=PublishStatus.PUBLISHED).count()
        published_chunks = Chunk.objects.filter(status=PublishStatus.PUBLISHED).count()
        embedded = Chunk.objects.filter(embedding__isnull=False).count()
        failed_jobs = IngestJob.objects.filter(status=JobStatus.FAILED).count()
        return {
            "documents": Document.objects.count(),
            "documents_published": published_docs,
            "chunks": Chunk.objects.count(),
            "chunks_published": published_chunks,
            "chunks_embedded": embedded,
            "matters": Matter.objects.count(),
            "flows": Flow.objects.count(),
            "terms": Term.objects.count(),
            "jobs_failed": failed_jobs,
        }

    def jobs(self, status: str | None = None, limit: int = 20) -> QuerySet[IngestJob]:
        qs = IngestJob.objects.select_related("document")
        if status:
            qs = qs.filter(status=status)
        return qs[:limit]

    def doc_type_counts(self) -> list[dict[str, Any]]:
        rows = (
            Document.objects.values("doc_type")
            .annotate(total=Count("id"))
            .order_by("doc_type")
        )
        return [{"doc_type": r["doc_type"], "total": r["total"]} for r in rows]


class WriteRepository(ReadRepository):
    """写入视图。仅 M11 / M14 / P6 运营侧使用。"""

    def find_by_checksum(self, checksum: str) -> Document | None:
        return Document.objects.filter(checksum=checksum).first()

    def latest_version(self, title: str, doc_type: str) -> int:
        last = (
            Document.objects.filter(title=title, doc_type=doc_type)
            .order_by("-version")
            .values_list("version", flat=True)
            .first()
        )
        return last or 0

    def archive_existing(self, title: str, doc_type: str) -> int:
        """同标题同类型的已发布旧版置为 archived，返回影响行数。

        块必须一起归档，否则旧版块仍会出现在 active_chunks 里。
        """
        ids = list(
            Document.objects.filter(
                title=title, doc_type=doc_type, status=PublishStatus.PUBLISHED
            ).values_list("id", flat=True)
        )
        if not ids:
            return 0
        Chunk.objects.filter(document_id__in=ids).update(
            status=PublishStatus.ARCHIVED, updated_at=timezone.now()
        )
        return Document.objects.filter(id__in=ids).update(
            status=PublishStatus.ARCHIVED, updated_at=timezone.now()
        )

    @transaction.atomic
    def create_document(self, **fields: Any) -> Document:
        return Document.objects.create(**fields)

    @transaction.atomic
    def bulk_chunks(
        self, document: Document, rows: list[dict[str, Any]], publish: bool
    ) -> int:
        status = PublishStatus.PUBLISHED if publish else PublishStatus.DRAFT
        objs = [
            Chunk(document=document, status=status, **row)
            for row in rows
        ]
        Chunk.objects.bulk_create(objs, batch_size=500)
        return len(objs)

    @transaction.atomic
    def publish(self, document: Document) -> Document:
        document.status = PublishStatus.PUBLISHED
        document.published_at = timezone.now()
        document.save(update_fields=["status", "published_at", "updated_at"])
        document.chunks.all().update(status=PublishStatus.PUBLISHED)
        return document

    @transaction.atomic
    def archive(self, document: Document) -> Document:
        document.status = PublishStatus.ARCHIVED
        document.save(update_fields=["status", "updated_at"])
        document.chunks.all().update(status=PublishStatus.ARCHIVED)
        return document

    def upsert_terms(self, rows: list[dict[str, Any]]) -> int:
        created = 0
        for row in rows:
            _, is_new = Term.objects.update_or_create(
                term=row["term"],
                canonical=row["canonical"],
                defaults={
                    "term_type": row.get("term_type", "alias"),
                    "weight": row.get("weight", 1),
                },
            )
            created += int(is_new)
        return created

    @transaction.atomic
    def upsert_matter(self, code: str, **fields: Any) -> Matter:
        matter, _ = Matter.objects.update_or_create(code=code, defaults=fields)
        return matter

    @transaction.atomic
    def replace_flows(self, matter: Matter, rows: list[dict[str, Any]]) -> int:
        """整套替换：步骤序号是相对顺序，逐条更新反而容易出现空洞。"""
        Flow.objects.filter(matter=matter).delete()
        if not rows:
            return 0
        Flow.objects.bulk_create([Flow(matter=matter, **row) for row in rows], batch_size=200)
        return len(rows)
