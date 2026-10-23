"""编排器：单轮落库、多子问题并行、部分失败兜底、超时兜底。"""

import asyncio
import uuid

import pytest

from apps.orchestrator import session
from apps.orchestrator.models import Conversation, Message
from apps.orchestrator.orchestrator import orc
from apps.qa.pipeline import qa
from apps.qa.types import Answer, Citation, Evidence, Intent, Understanding


def understanding(subs=None, intent=Intent.MATTER, original="学生证丢了怎么补办"):
    return Understanding(
        intent=intent,
        original=original,
        rewritten=original,
        sub_questions=subs or [],
        confidence=0.9,
    )


def make_answer(question: str, *, text: str = "到教务处学籍科办理。", chunk_id: int = 1) -> Answer:
    return Answer(
        question=question,
        intent="matter",
        answerable=True,
        text=text,
        citations=[
            Citation(
                ref=1,
                chunk_id=chunk_id,
                document_id=1,
                title="学生证补办",
                section="四、办理流程",
            )
        ],
        evidence=[
            Evidence(
                ref=1,
                chunk_id=chunk_id,
                document_id=1,
                title="学生证补办",
                doc_type="guide",
                dept="教务处",
                section="四、办理流程",
                page=1,
                content="到教务处学籍科提交申请。",
                score=0.9,
                fusion=1.0,
                source="both",
            )
        ],
        meta={},
    )


@pytest.fixture
def patch_understand(monkeypatch):
    def _apply(value):
        async def fake(question, *, audience="unknown", history=None):
            return value

        monkeypatch.setattr("apps.qa.understand.understand", fake)

    return _apply


@pytest.mark.django_db(transaction=True)
def test_single_turn_persists_and_remembers(monkeypatch, patch_understand):
    patch_understand(understanding())
    seen: list[list[tuple[str, str]] | None] = []

    async def fake_answer(question, *, audience="unknown", history=None, **kwargs):
        seen.append(history)
        return make_answer(question, text=f"答：{question}")

    monkeypatch.setattr(qa, "answer", fake_answer)

    first = asyncio.run(orc.turn("学生证丢了怎么补办", user_key="u1"))
    assert first.mode == "single"
    assert first.turn == 1
    assert first.answerable
    assert "答：学生证丢了怎么补办" in first.text

    conv = Conversation.objects.get(pk=first.conversation_id)
    assert conv.turn_count == 1
    assert conv.title == "学生证丢了怎么补办"
    roles = list(
        Message.objects.filter(conversation=conv)
        .order_by("turn", "role")
        .values_list("role", flat=True)
    )
    assert roles == ["assistant", "user"]      # 同轮内 assistant 字典序在前

    second = asyncio.run(
        orc.turn(
            "那要多久",
            user_key="u1",
            conversation_id=first.conversation_id,
        )
    )
    assert second.conversation_id == first.conversation_id
    assert second.turn == 2
    assert seen[1] and len(seen[1]) >= 2       # 第二轮带上了上一轮问答

    state = session.load(first.conversation_id)
    assert state is not None and state.turn == 2 and len(state.history) == 2


@pytest.mark.django_db(transaction=True)
def test_fanout_merges_segments(monkeypatch, patch_understand):
    patch_understand(understanding(subs=["要什么材料", "多久能办好"]))
    traces: list[str] = []

    async def fake_answer(question, *, audience="unknown", history=None, **kwargs):
        traces.append(kwargs.get("trace_id", ""))
        return make_answer(question, text=f"{question}的答案")

    monkeypatch.setattr(qa, "answer", fake_answer)

    result = asyncio.run(orc.turn("学生证补办要什么材料、多久能办好", user_key="u2"))
    assert result.mode == "fanout"
    assert len(result.segments) == 2
    assert "①" in result.text and "②" in result.text
    # 两段引用同一块：合并成一条，记下两段都用过
    assert len(result.citations) == 1
    assert result.citations[0]["segments"] == [0, 1]
    assert result.answerable
    # ai_calls.trace_id 是 UUID 字段：多段必须共用同一个合法 uuid，不能拼后缀
    assert len(set(traces)) == 1
    uuid.UUID(traces[0])


@pytest.mark.django_db(transaction=True)
def test_segment_failure_keeps_the_rest(monkeypatch, patch_understand):
    patch_understand(understanding(subs=["要什么材料", "多久能办好"]))

    async def fake_answer(question, *, audience="unknown", history=None, **kwargs):
        if "多久" in question:
            raise RuntimeError("boom")
        return make_answer(question, text="材料是身份证。")

    monkeypatch.setattr(qa, "answer", fake_answer)

    result = asyncio.run(orc.turn("学生证补办要什么材料、多久能办好", user_key="u3"))
    assert result.mode == "fanout"
    assert result.failed_segments == 1
    assert result.answerable is True            # 另一段还成立
    assert "没能生成" in result.segments[1].text
    assert result.segments[1].failed is True


@pytest.mark.django_db(transaction=True)
def test_segment_timeout_is_bounded(monkeypatch, patch_understand, settings):
    settings.ORC_SEGMENT_TIMEOUT = 0.05
    patch_understand(understanding())

    async def slow_answer(question, *, audience="unknown", history=None, **kwargs):
        await asyncio.sleep(0.3)
        return make_answer(question)

    monkeypatch.setattr(qa, "answer", slow_answer)

    result = asyncio.run(orc.turn("学生证丢了怎么补办", user_key="u4"))
    assert result.segments[0].failed is True
    assert "超时" in result.segments[0].text
    assert result.answerable is False
