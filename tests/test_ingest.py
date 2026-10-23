"""入库流水线：解析、写入、幂等、版本升级。

依赖 PG 与 MinIO（与 test_health 同口径，跑测试前须启动中间件）。
"""

import pytest

from apps.knowledge.ingest import process_file
from apps.knowledge.models import Chunk, Document, JobStatus, PublishStatus
from apps.knowledge.repositories import WriteRepository

SAMPLE = """# 学生证补办

## 一、办理条件

在籍本科生、研究生学生证遗失或损坏，可申请补办。每年最多补办两次。

## 二、所需材料

1. 本人身份证原件。
2. 一寸免冠照片一张。
3. 学生证补办申请表（教务处网站下载）。

## 三、办理流程

携带上述材料到教务处学籍科窗口提交，受理后三个工作日领取新证。

## 四、办理地点

行政楼 305 室，工作日 8:30-11:30、14:00-17:00 受理。

## 五、注意事项

补办期间可申请临时学生证明，用于购买火车票优惠。原学生证找回后应交回注销。
"""


@pytest.mark.django_db
def test_ingest_markdown_and_idempotent(tmp_path):
    path = tmp_path / "01-学生证补办.md"
    path.write_text(SAMPLE, encoding="utf-8")
    repo = WriteRepository()

    status, doc, msg, n = process_file(
        path, doc_type="guide", dept="教务处", publish=True, repo=repo, rel_path="guide/x.md"
    )
    assert status == JobStatus.SUCCEEDED, msg
    assert doc is not None
    assert doc.title == "学生证补办"
    assert doc.version == 1
    assert doc.status == PublishStatus.PUBLISHED
    assert n >= 1
    assert doc.chunks.exclude(search_text="").count() == n

    # 同一内容再导一次：命中 checksum，直接跳过
    again, doc2, _msg, n2 = process_file(
        path, doc_type="guide", dept="教务处", publish=True, repo=repo, rel_path="guide/x.md"
    )
    assert again == JobStatus.SKIPPED
    assert n2 == 0
    assert doc2.pk == doc.pk
    assert Document.objects.count() == 1


@pytest.mark.django_db
def test_ingest_new_content_bumps_version(tmp_path):
    """同名文件内容变更：版本 +1，旧版归档。"""
    repo = WriteRepository()
    path = tmp_path / "学生证补办.md"
    path.write_text(SAMPLE, encoding="utf-8")
    process_file(path, doc_type="guide", dept="教务处", publish=True, repo=repo)

    path.write_text(SAMPLE + "\n## 六、补充说明\n\n自 2025 年起可线上申请。\n", encoding="utf-8")
    status, doc, _msg, _n = process_file(
        path, doc_type="guide", dept="教务处", publish=True, repo=repo
    )

    assert status == JobStatus.SUCCEEDED
    assert doc.version == 2
    old = Document.objects.get(version=1)
    assert old.status == PublishStatus.ARCHIVED
    assert Chunk.objects.filter(document=old).first().status == PublishStatus.ARCHIVED


@pytest.mark.django_db
def test_empty_file_fails(tmp_path):
    path = tmp_path / "空文件.md"
    path.write_text("   \n\n", encoding="utf-8")
    status, doc, msg, _n = process_file(
        path, doc_type="faq", dept="", publish=False, repo=WriteRepository()
    )
    assert status == JobStatus.FAILED
    assert doc is None
    assert "text" in msg
