"""会话热状态：Redis 上下文、PG 重建、指代窗口裁剪。"""

import pytest

from apps.orchestrator import session
from apps.orchestrator.models import Conversation, Message


@pytest.mark.django_db
def test_create_and_load_roundtrip():
    state = session.create("u1", "undergrad")
    assert state.conversation_id
    loaded = session.load(state.conversation_id)
    assert loaded is not None
    assert loaded.user_key == "u1"
    assert loaded.audience == "undergrad"


@pytest.mark.django_db
def test_append_turn_trims_history(settings):
    settings.ORC_HISTORY_TURNS = 2
    state = session.create("u1")
    for i in range(5):
        state.turn += 1
        session.append_turn(state, f"问题{i}", f"答案{i}", matter=f"事项{i}", intent="matter")

    loaded = session.load(state.conversation_id)
    assert loaded is not None
    assert len(loaded.history) == 2
    assert loaded.history[-1]["q"] == "问题4"
    assert loaded.last_matter == "事项4"


@pytest.mark.django_db
def test_rebuild_from_db_when_redis_lost():
    """Redis 丢键不该导致上下文断裂：从最近消息重建。"""
    state = session.create("u1")
    conv = Conversation.objects.get(pk=state.conversation_id)
    Message.objects.create(
        conversation=conv, turn=1, role=Message.Role.USER, content="学生证怎么补办"
    )
    Message.objects.create(
        conversation=conv,
        turn=1,
        role=Message.Role.ASSISTANT,
        content="到教务处学籍科办理。",
        intent="matter",
        answerable=True,
        payload={"matter_name": "学生证补办"},
    )
    conv.turn_count = 1
    conv.save(update_fields=["turn_count"])
    session.clear(state.conversation_id)

    rebuilt = session.load(state.conversation_id)
    assert rebuilt is not None
    assert rebuilt.turn == 1
    assert rebuilt.history == [{"q": "学生证怎么补办", "a": "到教务处学籍科办理。"}]
    assert rebuilt.last_matter == "学生证补办"


@pytest.mark.django_db
def test_load_or_create_with_foreign_conversation_id():
    """别人的会话 id 不报错，直接新建——前端不用处理这种边界。"""
    mine = session.create("u1")
    other = session.load_or_create(mine.conversation_id, user_key="u2")
    assert other.conversation_id != mine.conversation_id
    assert other.user_key == "u2"


@pytest.mark.django_db
def test_history_pairs_shape(settings):
    settings.ORC_HISTORY_TURNS = 3
    state = session.create("u1")
    session.append_turn(state, "Q1", "A1")
    session.append_turn(state, "Q2", "A2")
    pairs = state.history_pairs()
    assert pairs == [("user", "Q1"), ("assistant", "A1"), ("user", "Q2"), ("assistant", "A2")]
