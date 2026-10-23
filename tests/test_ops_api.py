"""知识运营：上传入库、发布回滚、冲突检测、事项词典、模型槽位、向量补充。"""

import json

import pytest
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from apps.gateway import overrides, router
from apps.gateway.gateway import gateway
from apps.gateway.models import ModelSetting
from apps.knowledge import queue
from apps.knowledge.models import Chunk, Document, IngestJob, Matter, PublishStatus, Term

ADMIN = {"HTTP_X_DEMO_TOKEN": "admin-demo"}

MD = """# {title}

## 一、所需材料

1. 本人校园卡。
2. 申请表格一份。

## 二、办理流程

第一步：到窗口提交申请。
第二步：受理后 3 个工作日领取。

## 三、收费标准

每份 {price} 元。
"""


@pytest.fixture(autouse=True)
def _tmp_upload_dir(settings, tmp_path):
    """每个用例一个暂存目录：原件留在真实目录里会让下一次同内容上传直接 409。"""
    settings.OPS_UPLOAD_DIR = str(tmp_path / "uploads")


def client() -> Client:
    return Client(SERVER_NAME="localhost")


def post_json(c: Client, url: str, payload):
    return c.post(url, data=json.dumps(payload), content_type="application/json", **ADMIN)


def upload(c: Client, title: str, *, price: int = 2, name: str | None = None, doc_type="guide"):
    body = MD.format(title=title, price=price).encode("utf-8")
    file = SimpleUploadedFile(name or f"{title}.md", body, content_type="text/markdown")
    return c.post(
        "/api/ops/uploads",
        data={"file": file, "doc_type": doc_type, "dept": "图书馆"},
        **ADMIN,
    )


def ingest(c: Client, title: str, *, price: int = 2) -> Document:
    response = upload(c, title, price=price)
    assert response.status_code == 200, response.content
    queue.process_job(response.json()["job_id"])
    doc = Document.objects.filter(title=title).order_by("-version").first()
    assert doc is not None
    return doc


@pytest.mark.django_db
def test_upload_validates_suffix_and_duplicate():
    c = client()
    bad = SimpleUploadedFile("x.exe", b"binary", content_type="application/octet-stream")
    bad_response = c.post(
        "/api/ops/uploads", data={"file": bad, "doc_type": "guide"}, **ADMIN
    )
    assert bad_response.status_code == 400

    assert upload(c, "唯一文档A").status_code == 200
    assert upload(c, "唯一文档A").status_code == 409      # checksum 相同


@pytest.mark.django_db
def test_ingest_then_publish_invalidates_cache():
    c = client()
    doc = ingest(c, "测试发布流程")
    assert doc.status == PublishStatus.DRAFT
    assert doc.chunks.count() > 0

    review = c.get("/api/ops/review", **ADMIN).json()
    assert any(row["id"] == doc.pk for row in review)

    cache.set("gw:kb:fingerprint", "stale")
    response = c.post(f"/api/ops/review/{doc.pk}/publish", **ADMIN)
    assert response.status_code == 200
    doc.refresh_from_db()
    assert doc.status == PublishStatus.PUBLISHED
    assert cache.get("gw:kb:fingerprint") is None          # 知识换版必须立刻失效

    assert c.post(f"/api/ops/review/{doc.pk}/publish", **ADMIN).status_code == 409


@pytest.mark.django_db
def test_new_version_archives_old_and_rollback():
    c = client()
    v1 = ingest(c, "测试回滚流程", price=2)
    assert c.post(f"/api/ops/review/{v1.pk}/publish", **ADMIN).status_code == 200

    v2 = ingest(c, "测试回滚流程", price=5)
    assert v2.version == 2
    assert c.post(f"/api/ops/review/{v2.pk}/publish", **ADMIN).status_code == 200
    v1.refresh_from_db()
    assert v1.status == PublishStatus.ARCHIVED              # 同标题旧版自动归档

    assert c.post(f"/api/ops/documents/{v1.pk}/rollback", **ADMIN).status_code == 200
    v1.refresh_from_db()
    v2.refresh_from_db()
    assert v1.status == PublishStatus.PUBLISHED
    assert v2.status == PublishStatus.ARCHIVED


@pytest.mark.django_db
def test_conflict_is_flagged_before_publish():
    c = client()
    v1 = ingest(c, "测试冲突检测", price=2)
    c.post(f"/api/ops/review/{v1.pk}/publish", **ADMIN)

    v2 = ingest(c, "测试冲突检测", price=5)
    row = [r for r in c.get("/api/ops/review", **ADMIN).json() if r["id"] == v2.pk][0]
    assert row["conflicts"], "同事项费用不同应报冲突"
    conflict = row["conflicts"][0]
    assert conflict["field"] == "费用"
    assert "5" in conflict["draft"] and "2" in conflict["published"]


@pytest.mark.django_db
def test_jobs_retry_resets_status():
    c = client()
    job = IngestJob.objects.create(source_path="/tmp/not-exists.md", doc_type="guide")
    IngestJob.objects.filter(pk=job.pk).update(status="failed", message="boom")

    assert c.post(f"/api/ops/jobs/{job.pk}/retry", **ADMIN).status_code == 200
    job.refresh_from_db()
    assert job.status == "pending" and job.message == ""


@pytest.mark.django_db
def test_terms_upsert_then_delete_clears_cache():
    c = client()
    cache.set("qa:terms", {"旧词": "旧"})
    body = [{"term": "老卡", "canonical": "校园卡", "term_type": "alias", "weight": 2}]
    assert post_json(c, "/api/ops/terms", body).status_code == 200
    assert Term.objects.filter(term="老卡", canonical="校园卡").exists()
    assert cache.get("qa:terms") is None                    # 词典缓存必须失效

    term = Term.objects.get(term="老卡")
    assert c.delete(f"/api/ops/terms/{term.pk}", **ADMIN).status_code == 200
    assert not Term.objects.filter(pk=term.pk).exists()


@pytest.mark.django_db
def test_matter_upsert_keeps_code():
    c = client()
    payload = {
        "name": "测试事项X",
        "dept": "教务处",
        "location": "行政楼 101",
        "audience": "undergrad",
    }
    first = post_json(c, "/api/ops/matters", payload)
    assert first.status_code == 200
    code = first.json()["code"]

    payload["location"] = "行政楼 202"
    payload["code"] = code
    second = post_json(c, "/api/ops/matters", payload)
    assert second.json()["code"] == code
    assert Matter.objects.filter(code=code).count() == 1
    assert Matter.objects.get(code=code).location == "行政楼 202"


@pytest.mark.django_db
def test_model_override_reaches_router():
    c = client()
    try:
        response = c.put(
            "/api/ops/models/main",
            data=json.dumps({"model": "override-model", "note": "压测"}),
            content_type="application/json",
            **ADMIN,
        )
        assert response.status_code == 200
        assert response.json()["model"] == "override-model"
        assert response.json()["overridden"] is True
        assert router.main_adapter().model == "override-model"

        slots = {row["slot"]: row for row in c.get("/api/ops/models", **ADMIN).json()}
        assert slots["main"]["overridden"] is True
        assert slots["embed"]["overridden"] is False          # 未改的槽位仍跟随 .env
    finally:
        ModelSetting.objects.filter(slot="main").delete()
        overrides.invalidate()
    assert router.main_adapter().model != "override-model"


@pytest.mark.django_db(transaction=True)
def test_embed_endpoint_fills_vectors(monkeypatch):
    c = client()
    doc = ingest(c, "测试补向量")
    assert Chunk.objects.filter(document=doc, embedding__isnull=True).exists()

    async def fake_embed(texts, kind="doc"):
        return [[0.01] * 1023 + [1.0] for _ in texts]

    monkeypatch.setattr(gateway, "embed", fake_embed)
    response = c.post(f"/api/ops/documents/{doc.pk}/embed", **ADMIN)
    assert response.status_code == 200
    assert response.json()["filled"] > 0
    assert not Chunk.objects.filter(document=doc, embedding__isnull=True).exists()


@pytest.mark.django_db
def test_dashboard_shape():
    body = client().get("/api/ops/dashboard", **ADMIN).json()
    assert {"documents", "chunks", "jobs", "qa_24h", "matters", "terms"} <= set(body)
    assert "queue_depth" in body
    assert set(body["qa_24h"]) == {"turns", "refused", "refusal_rate", "p50_ms", "p95_ms"}
