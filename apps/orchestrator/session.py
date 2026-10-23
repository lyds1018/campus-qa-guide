"""会话热状态：Redis 只放"下一轮要用"的东西。

| 存 | 不存 |
| --- | --- |
| 历史窗口（问句 + 答案首段）、槽位、上一轮事项与意图、待补信息 |
| 完整答案 JSON（在 `messages.payload` 里）、证据正文（体积大且可重查） |

Redis 丢了不致命：`load_or_create` 会从 PG 的最近消息重建上下文窗口，只是丢掉
"上一轮事项"这类快捷字段。反过来，PG 无法从 Redis 恢复历史会话列表。
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from apps.orchestrator.models import Conversation, Message

logger = logging.getLogger(__name__)

KEY = "orc:sess:{}"


@dataclass
class SessionState:
    conversation_id: str
    user_key: str = "demo"
    audience: str = "unknown"
    turn: int = 0
    history: list[dict] = field(default_factory=list)  # [{"q": ..., "a": ...}]
    last_matter: str = ""
    last_intent: str = ""
    pending: str = ""

    def history_pairs(self) -> list[tuple[str, str]]:
        """给 M5 做指代还原用：问句 + 答案，按时间正序。"""
        pairs: list[tuple[str, str]] = []
        for row in self.history[-settings.ORC_HISTORY_TURNS :]:
            if row.get("q"):
                pairs.append(("user", row["q"]))
            if row.get("a"):
                pairs.append(("assistant", row["a"]))
        return pairs


def _key(conversation_id: str) -> str:
    return KEY.format(conversation_id)


def _dump(state: SessionState) -> str:
    return json.dumps(asdict(state), ensure_ascii=False)


def _load_cache(conversation_id: str) -> SessionState | None:
    raw = cache.get(_key(conversation_id))
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None
    known = {f for f in SessionState.__dataclass_fields__}
    return SessionState(**{k: v for k, v in data.items() if k in known})


def _rebuild_from_db(conversation_id: str) -> SessionState | None:
    """Redis 丢失后的重建：只回填最近 N 轮问答与最后一条助手消息的意图/事项。"""
    conv = Conversation.objects.filter(pk=conversation_id).first()
    if conv is None:
        return None
    rows = list(
        Message.objects.filter(conversation=conv)
        .order_by("-turn", "-id")[: settings.ORC_HISTORY_TURNS * 2]
    )
    rows.reverse()
    history: list[dict] = []
    last_matter = ""
    last_intent = ""
    for msg in rows:
        if msg.role == Message.Role.USER:
            history.append({"q": msg.content, "a": ""})
        elif history and not history[-1]["a"]:
            history[-1]["a"] = msg.content[:200]
            last_intent = msg.intent or last_intent
            last_matter = (msg.payload or {}).get("matter_name") or last_matter
    return SessionState(
        conversation_id=str(conv.pk),
        user_key=conv.user_key,
        audience=conv.audience,
        turn=conv.turn_count,
        history=history[-settings.ORC_HISTORY_TURNS :],
        last_matter=last_matter,
        last_intent=last_intent,
    )


def load(conversation_id: str | None) -> SessionState | None:
    if not conversation_id:
        return None
    state = _load_cache(str(conversation_id))
    if state is not None:
        return state
    state = _rebuild_from_db(str(conversation_id))
    if state is not None:
        save(state)  # 回填缓存，下一轮不必再查库
    return state


def create(user_key: str = "demo", audience: str = "unknown") -> SessionState:
    conv = Conversation.objects.create(
        user_key=user_key or "demo",
        audience=audience or "unknown",
        last_active_at=timezone.now(),
    )
    state = SessionState(
        conversation_id=str(conv.pk), user_key=conv.user_key, audience=conv.audience
    )
    save(state)
    return state


def load_or_create(
    conversation_id: str | None, user_key: str = "demo", audience: str = "unknown"
) -> SessionState:
    """会话 id 传错（别人的 / 已删）时新建，不报错——前端不需要处理这种边界。"""
    state = load(conversation_id)
    if state is not None and (not user_key or state.user_key == user_key):
        if audience not in ("", "unknown", None):
            state.audience = audience
        return state
    return create(user_key, audience)


def save(state: SessionState) -> None:
    cache.set(_key(state.conversation_id), _dump(state), settings.ORC_SESSION_TTL)


def append_turn(
    state: SessionState, question: str, answer_text: str, *, matter: str = "", intent: str = ""
) -> None:
    state.history.append({"q": question, "a": answer_text[:200]})
    state.history = state.history[-settings.ORC_HISTORY_TURNS :]
    if matter:
        state.last_matter = matter
    if intent:
        state.last_intent = intent
    save(state)


def clear(conversation_id: str) -> None:
    """清上下文但保留消息留痕：P5 的"新对话"应新建会话，这个接口用于清指代。"""
    cache.delete(_key(str(conversation_id)))


def recent(user_key: str = "demo", limit: int = 20) -> list[Conversation]:
    return list(Conversation.objects.filter(user_key=user_key)[: max(1, min(limit, 100))])
