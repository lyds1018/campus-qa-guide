"""接入层：鉴权、角色门槛、追踪、审计、导出、会话隔离。"""

import json

import pytest
from django.test import Client

from apps.access.models import ApiLog
from apps.orchestrator.models import Conversation, Message

STUDENT = {"HTTP_X_DEMO_TOKEN": "student-demo"}
ADMIN = {"HTTP_X_DEMO_TOKEN": "admin-demo"}


def client() -> Client:
    return Client(SERVER_NAME="localhost")


@pytest.mark.django_db
def test_missing_token_is_401():
    response = client().get("/api/chat/me")
    assert response.status_code == 401
    assert "X-Demo-Token" in response.json()["detail"]


@pytest.mark.django_db
def test_identity_and_limits():
    response = client().get("/api/chat/me", **STUDENT)
    assert response.status_code == 200
    body = response.json()
    assert body["role"] == "student"
    assert body["audience"] == "undergrad"
    assert body["limits"]["chat"] > 0
    assert response["X-RateLimit-Remaining"].isdigit()


@pytest.mark.django_db
def test_ops_requires_admin():
    assert client().get("/api/ops/dashboard", **STUDENT).status_code == 403
    assert client().get("/api/ops/dashboard", **ADMIN).status_code == 200


@pytest.mark.django_db
def test_trace_id_is_echoed_and_audited():
    response = client().get("/api/chat/me", HTTP_X_TRACE_ID="trace-from-client", **STUDENT)
    assert response["X-Trace-Id"] == "trace-from-client"
    row = ApiLog.objects.filter(trace_id="trace-from-client").first()
    assert row is not None
    assert row.path == "/api/chat/me"
    assert row.status == 200
    assert row.role == "student"


@pytest.mark.django_db
def test_rejected_requests_are_audited_too():
    client().get("/api/chat/me")                      # 401
    assert ApiLog.objects.filter(path="/api/chat/me", status=401).exists()


@pytest.mark.django_db
def test_sessions_are_scoped_to_identity():
    now = "2026-10-23T10:00:00Z"
    mine = Conversation.objects.create(
        user_key="demo-student", title="我的会话", last_active_at=now
    )
    other = Conversation.objects.create(
        user_key="someone", title="别人的会话", last_active_at=now
    )
    Message.objects.create(
        conversation=mine, turn=1, role=Message.Role.USER, content="学生证怎么补办"
    )

    c = client()
    rows = c.get("/api/chat/sessions", **STUDENT).json()
    assert [r["id"] for r in rows] == [str(mine.pk)]
    detail = c.get(f"/api/chat/sessions/{mine.pk}", **STUDENT).json()
    assert detail[0]["content"] == "学生证怎么补办"
    # 别人的会话按"不存在"处理，不暴露存在性
    assert c.get(f"/api/chat/sessions/{other.pk}", **STUDENT).json() == []


@pytest.mark.django_db
def test_export_returns_utf8_bom_csv():
    payload = {
        "title": "学生证补办",
        "question": "学生证丢了怎么补办",
        "items": [
            {"kind": "material", "text": "身份证原件", "checked": True},
            {"kind": "step", "text": "到窗口核验", "checked": False},
        ],
    }
    response = client().post(
        "/api/chat/export",
        data=json.dumps(payload),
        content_type="application/json",
        **STUDENT,
    )
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/csv")
    assert "attachment" in response["Content-Disposition"]
    body = response.content.decode("utf-8")
    assert body.startswith("\ufeff")                    # Excel 双击不乱码
    assert "材料" in body and "√" in body


@pytest.mark.django_db
def test_export_requires_auth():
    response = client().post("/api/chat/export", data="{}", content_type="application/json")
    assert response.status_code == 401
