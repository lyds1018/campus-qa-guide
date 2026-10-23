"""M6 检索：中文全文命中、向量召回、RRF 归一、门槛与重排降级。"""

import asyncio

import pytest
from django.utils import timezone

from apps.gateway.base import RankedDoc
from apps.gateway.gateway import gateway
from apps.knowledge.chunking import tokenize
from apps.knowledge.models import Chunk, Document, PublishStatus
from apps.qa import retrieve

VEC = [0.01] * 1023 + [1.0]


def make_doc(title: str, sections: list[tuple[str, str]], vec: list[float] | None = VEC):
    doc = Document.objects.create(
        title=title,
        doc_type="guide",
        source_path=f"{title}.md",
        object_key=f"raw/{title}",
        checksum=f"ck-{title}",
        status=PublishStatus.PUBLISHED,
        published_at=timezone.now(),
    )
    for i, (section, body) in enumerate(sections):
        Chunk.objects.create(
            document=doc,
            ordinal=i,
            content=f"{section}\n{body}",
            search_text=tokenize(body),
            meta={"section_path": [title, section], "page": 1},
            embedding=vec,
            status=PublishStatus.PUBLISHED,
        )
    return doc


@pytest.mark.django_db
def test_fts_recall_hits_chinese_lexemes():
    body = "学生证补办所需材料：本人身份证原件与一寸免冠照片一张"
    make_doc("学生证补办", [("三、所需材料", body)])
    cands, _, n_fts = retrieve._recall("学生证补办要什么材料", None, None)
    assert n_fts >= 1
    assert cands and cands[0]["title"] == "学生证补办"
    assert cands[0]["source"] in ("fts", "both")


@pytest.mark.django_db
def test_fts_ignores_unrelated_query():
    make_doc("学生证补办", [("三、所需材料", "本人身份证原件")])
    _, _, n_fts = retrieve._recall("游泳馆开放时间", None, None)
    assert n_fts == 0


def test_fuse_normalizes_by_available_lists():
    both = retrieve.fuse([1, 2], [1, 3])
    assert both[1] == pytest.approx(1.0)          # 两路都第一
    assert both[2] == pytest.approx((1 / 62) / (2 / 61))   # 单路第二，按双路基准归一

    single = retrieve.fuse([1, 2], [])
    assert single[1] == pytest.approx(1.0)        # 只有一路时基准收窄
    assert single[2] < single[1]
    assert retrieve.fuse([], []) == {}


@pytest.mark.django_db(transaction=True)
def test_retrieve_gate_passes_on_strong_match(monkeypatch):
    make_doc("学生证补办", [("三、所需材料", "本人身份证原件与一寸免冠照片一张")])

    async def fake_embed(texts, kind="doc"):
        return [VEC for _ in texts]

    async def no_rerank(query, docs, top_k=10):
        return []

    monkeypatch.setattr(gateway, "embed", fake_embed)
    monkeypatch.setattr(gateway, "rerank", no_rerank)

    result = asyncio.run(retrieve.retrieve("学生证补办要什么材料"))
    assert result.answerable
    assert result.reranked is False
    assert result.evidence[0].title == "学生证补办"
    assert result.evidence[0].ref == 1


@pytest.mark.django_db(transaction=True)
def test_retrieve_refuses_unrelated(monkeypatch):
    """向量召回永远能排出"第一名"，所以门槛必须卡绝对相似度，不能看融合分。"""
    make_doc("学生证补办", [("三、所需材料", "本人身份证原件")])
    far = [1.0] + [0.01] * 1023          # 与库内向量近乎正交，相似度极低

    async def fake_embed(texts, kind="doc"):
        return [far for _ in texts]

    async def no_rerank(query, docs, top_k=10):
        return []

    monkeypatch.setattr(gateway, "embed", fake_embed)
    monkeypatch.setattr(gateway, "rerank", no_rerank)

    result = asyncio.run(retrieve.retrieve("游泳馆几点开门"))
    assert not result.answerable
    assert result.reason == "low_confidence"
    assert result.vector_hits == 1          # 召回确实返回了一块，只是不够近


@pytest.mark.django_db(transaction=True)
def test_rerank_reorders_and_degrades(monkeypatch):
    make_doc("学生证补办", [("三、所需材料", "本人身份证原件"), ("四、办理流程", "到教务处窗口")])

    async def fake_embed(texts, kind="doc"):
        return [VEC for _ in texts]

    async def fake_rerank(query, docs, top_k=10):
        # 把最后一块排到第一：验证排序真的跟重排走
        return [RankedDoc(index=len(docs) - 1, score=0.91), RankedDoc(index=0, score=0.72)]

    monkeypatch.setattr(gateway, "embed", fake_embed)
    monkeypatch.setattr(gateway, "rerank", fake_rerank)

    result = asyncio.run(retrieve.retrieve("学生证补办要什么材料"))
    assert result.reranked is True
    assert result.evidence[0].section == "四、办理流程"
    assert result.evidence[0].score == pytest.approx(0.91)
