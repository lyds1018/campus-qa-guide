"""仓储层：读写分离与时效过滤。"""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.knowledge.models import Chunk, Document, PublishStatus
from apps.knowledge.repositories import ReadRepository, WriteRepository


def _doc(**kwargs) -> Document:
    base = {
        "title": "学生证补办",
        "doc_type": "guide",
        "dept": "教务处",
        "source_path": "guide/学生证补办.md",
        "object_key": "raw/guide/ab/abc.md",
        "checksum": "a" * 64,
        "status": PublishStatus.PUBLISHED,
    }
    base.update(kwargs)
    return Document.objects.create(**base)


@pytest.mark.django_db
def test_read_only_sees_published():
    _doc(checksum="1" * 64)
    _doc(checksum="2" * 64, status=PublishStatus.DRAFT, title="草稿文档")
    _doc(checksum="3" * 64, status=PublishStatus.ARCHIVED, title="归档文档")

    repo = ReadRepository()
    titles = list(repo.documents().values_list("title", flat=True))
    assert titles == ["学生证补办"]


@pytest.mark.django_db
def test_expired_chunk_hidden():
    """active_chunks 是 P3 的召回入口，必须过滤掉过期文档。"""
    today = timezone.localdate()
    expired = _doc(checksum="4" * 64, title="已过期", effective_to=today - timedelta(days=1))
    alive = _doc(checksum="5" * 64, title="未过期", effective_to=None)
    for doc in (expired, alive):
        Chunk.objects.create(
            document=doc,
            ordinal=0,
            content="正文",
            search_text="正文",
            status=PublishStatus.PUBLISHED,
        )

    titles = set(
        ReadRepository().active_chunks().values_list("document__title", flat=True)
    )
    assert "未过期" in titles
    assert "已过期" not in titles


@pytest.mark.django_db
def test_write_repository_versions():
    repo = WriteRepository()
    assert repo.latest_version("学生证补办", "guide") == 0

    _doc(checksum="7" * 64, version=1)
    assert repo.latest_version("学生证补办", "guide") == 1

    repo.archive_existing("学生证补办", "guide")
    assert Document.objects.get(checksum="7" * 64).status == PublishStatus.ARCHIVED


@pytest.mark.django_db
def test_publish_syncs_chunks():
    doc = _doc(checksum="8" * 64, status=PublishStatus.DRAFT, title="待发布")
    Chunk.objects.create(
        document=doc, ordinal=0, content="正文", search_text="正文", status=PublishStatus.DRAFT
    )

    WriteRepository().publish(doc)
    doc.refresh_from_db()
    assert doc.status == PublishStatus.PUBLISHED
    assert doc.published_at is not None
    assert doc.chunks.first().status == PublishStatus.PUBLISHED


@pytest.mark.django_db
def test_stats_shape():
    _doc(checksum="9" * 64)
    stats = ReadRepository().stats()
    assert stats["documents"] >= 1
    assert stats["documents_published"] >= 1
    assert set(stats) >= {"chunks", "chunks_embedded", "jobs_failed", "terms"}
