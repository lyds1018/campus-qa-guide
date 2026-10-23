"""M5–M9 串联：可答、引用、清单、修复重写、拒答。

模型与向量全部打桩，不依赖外部供应商；数据库用真库（召回必须走真 SQL）。
"""

import asyncio

import pytest
from django.utils import timezone

from apps.gateway.base import ChatDelta, ChatResult
from apps.gateway.gateway import gateway
from apps.knowledge.chunking import tokenize
from apps.knowledge.models import Chunk, Document, PublishStatus
from apps.qa.pipeline import qa
from apps.qa.types import RefusalReason
from apps.qa.understand import UnderstandOut

VEC = [0.01] * 1023 + [1.0]


def make_doc(title, sections, vec=VEC):
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

EVIDENCE = [
    ("三、所需材料", "1. 本人身份证原件。\n2. 一寸免冠照片一张。"),
    ("四、办理流程", "第一步：到教务处学籍科窗口提交申请。\n第二步：受理后 3 个工作日领取新证。"),
]


def _result(text: str) -> ChatResult:
    return ChatResult(
        text=text,
        model="fake-chat",
        provider="main",
        finish_reason="stop",
        prompt_tokens=100,
        completion_tokens=50,
        degraded=False,
        trace_id="t",
    )


@pytest.fixture
def stubs(monkeypatch):
    async def fake_embed(texts, kind="doc"):
        return [[0.01] * 1023 + [1.0] for _ in texts]

    async def no_rerank(query, docs, top_k=10):
        return []

    async def fake_json(messages, *, schema, role="aux"):
        return UnderstandOut(
            intent="matter", rewritten="学生证补办", confidence=0.93, audience="undergrad"
        )

    monkeypatch.setattr(gateway, "embed", fake_embed)
    monkeypatch.setattr(gateway, "rerank", no_rerank)
    monkeypatch.setattr(gateway, "chat_json", fake_json)
    return monkeypatch


@pytest.mark.django_db(transaction=True)
def test_answer_with_citations_and_checklist(stubs):
    make_doc("学生证补办", EVIDENCE)
    calls = {"n": 0}

    async def fake_chat(messages, *, role="main", params=None, trace_id=None):
        calls["n"] += 1
        return _result(
            "到教务处学籍科窗口提交申请[1]。材料为身份证原件与一寸照片[1]，"
            "受理后 3 个工作日领取[1]。"
        )

    stubs.setattr(gateway, "chat", fake_chat)

    answer = asyncio.run(qa.answer("学生证丢了怎么补办"))
    assert answer.answerable
    assert answer.citations and answer.citations[0].ref == 1
    assert answer.checks is not None and answer.checks.ok
    assert calls["n"] == 1                                   # 一次就过，不触发修复
    kinds = {i.kind for i in answer.checklist}
    assert "material" in kinds
    assert answer.matter is not None and answer.matter.name == "学生证补办"
    assert answer.slots.audience == "undergrad"


@pytest.mark.django_db(transaction=True)
def test_answer_repairs_once_then_passes(stubs):
    make_doc("学生证补办", EVIDENCE)
    texts = iter(
        [
            "到教务处学籍科窗口提交申请，受理后 3 个工作日领取。",   # 一个引用都没有
            "到教务处学籍科窗口提交申请[1]，受理后 3 个工作日领取[1]。",
        ]
    )

    async def fake_chat(messages, *, role="main", params=None, trace_id=None):
        return _result(next(texts))

    stubs.setattr(gateway, "chat", fake_chat)

    answer = asyncio.run(qa.answer("学生证丢了怎么补办"))
    assert answer.answerable
    assert answer.checks is not None and answer.checks.ok
    assert answer.meta["repaired"] is True


@pytest.mark.django_db(transaction=True)
def test_ungrounded_answer_is_refused(stubs):
    make_doc("学生证补办", EVIDENCE)

    async def fake_chat(messages, *, role="main", params=None, trace_id=None):
        # 一直不给引用，修复也救不回来
        return _result("到教务处学籍科窗口提交申请，受理后 3 个工作日领取。")

    stubs.setattr(gateway, "chat", fake_chat)

    answer = asyncio.run(qa.answer("学生证丢了怎么补办"))
    assert not answer.answerable
    assert answer.refusal_reason == RefusalReason.UNGROUNDED.value
    assert "学籍科" in answer.text                          # 拒答时仍给原文出处


@pytest.mark.django_db(transaction=True)
def test_no_evidence_refusal(stubs):
    answer = asyncio.run(qa.answer("游泳馆几点开门"))
    assert not answer.answerable
    assert answer.refusal_reason == RefusalReason.NO_EVIDENCE.value


@pytest.mark.django_db(transaction=True)
def test_smalltalk_short_circuits_without_model(stubs):
    async def greeting_json(messages, *, schema, role="aux"):
        return UnderstandOut(intent="smalltalk", rewritten="你好", confidence=0.99)

    def boom(*args, **kwargs):
        raise AssertionError("寒暄不应该走生成")

    stubs.setattr(gateway, "chat_json", greeting_json)
    stubs.setattr(gateway, "chat", boom)
    answer = asyncio.run(qa.answer("你好"))
    assert answer.answerable
    assert "办事流程" in answer.text


@pytest.mark.django_db(transaction=True)
def test_stream_emits_stage_delta_final(stubs):
    make_doc("学生证补办", EVIDENCE)

    async def fake_stream(messages, *, role="main", params=None, trace_id=None):
        for piece in ("到教务处学籍科窗口提交[1]，", "受理后 3 个工作日领取[1]。"):
            yield ChatDelta(text=piece)

    stubs.setattr(gateway, "chat_stream", fake_stream)

    async def collect():
        return [e async for e in qa.answer_stream("学生证丢了怎么补办")]

    events = asyncio.run(collect())
    types = [e.type for e in events]
    assert "stage" in types and "delta" in types and types[-1] == "final"
    final = events[-1].answer
    assert final is not None and final.answerable and final.citations
    assert final.meta["stream"] is True
