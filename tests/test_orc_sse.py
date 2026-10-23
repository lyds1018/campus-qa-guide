"""SSE 协议：帧格式、事件顺序、心跳、收尾。"""

import asyncio
import json
import re

import pytest

from apps.orchestrator import events
from apps.orchestrator.models import Conversation
from apps.orchestrator.orchestrator import orc
from apps.qa.types import Intent, Understanding


def frame_events(frames: list[str]) -> list[str]:
    return [m.group(1) for m in re.finditer(r"^event: (\w+)$", "".join(frames), re.M)]


def frame_data(frames: list[str], event: str) -> dict:
    text = "".join(frames)
    pattern = rf"^event: {event}\ndata: (.*)$"
    match = re.search(pattern, text, re.M)
    assert match, f"没有 {event} 帧"
    return json.loads(match.group(1))


def test_sse_frame_is_two_lines_and_keeps_chinese():
    frame = events.sse(events.DELTA, {"text": "学生证补办"})
    assert frame.startswith("event: delta\ndata: ")
    assert frame.endswith("\n\n")
    assert "学生证补办" in frame                      # 不转义成 \uXXXX
    assert json.loads(frame.split("data: ", 1)[1]) == {"text": "学生证补办"}


def test_heartbeat_when_upstream_is_slow():
    async def slow():
        await asyncio.sleep(0.05)
        yield "event: delta\ndata: {\"text\": \"最后\"}\n\n"

    async def collect():
        return [f async for f in events.with_heartbeat(slow(), interval=0.01)]

    frames = asyncio.run(collect())
    assert frames[0] == events.HEARTBEAT
    assert ": ping" in "".join(frames[:-1])
    assert frames[-1].startswith("event: delta")


@pytest.mark.django_db(transaction=True)
def test_stream_order_for_direct_intent(monkeypatch):
    async def fake_understand(question, *, audience="unknown", history=None):
        return Understanding(
            intent=Intent.SMALLTALK,
            original=question,
            rewritten=question,
            confidence=0.99,
        )

    monkeypatch.setattr("apps.qa.understand.understand", fake_understand)

    async def collect():
        return [f async for f in orc.stream("你好", user_key="sse-1")]

    frames = asyncio.run(collect())
    names = frame_events(frames)
    assert names[0] == events.SESSION
    assert names[-1] == events.DONE
    assert events.DELTA in names and events.ANSWER in names
    assert events.STAGE in names                      # 至少一次进度

    session_payload = frame_data(frames, events.SESSION)
    assert session_payload["turn"] == 1
    assert Conversation.objects.filter(pk=session_payload["conversation_id"]).exists()

    done = frame_data(frames, events.DONE)
    assert done["turn"] == 1
    assert "latency_ms" in done and "trace_id" in done

    answer = frame_data(frames, events.ANSWER)
    assert answer["answerable"] is True
    assert "办事流程" in answer["text"]               # 寒暄的确定性话术


@pytest.mark.django_db(transaction=True)
def test_stream_error_still_ends_with_done(monkeypatch):
    async def boom(question, *, audience="unknown", history=None):
        raise RuntimeError("understand down")

    monkeypatch.setattr("apps.qa.understand.understand", boom)

    async def collect():
        return [f async for f in orc.stream("学生证丢了怎么补办", user_key="sse-2")]

    frames = asyncio.run(collect())
    names = frame_events(frames)
    assert events.ERROR in names
    assert names[-1] == events.DONE
