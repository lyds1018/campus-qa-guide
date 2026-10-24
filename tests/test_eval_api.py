"""反馈归因与评测只读接口。"""

import json

import pytest
from django.test import Client
from django.utils import timezone

from apps.eval.models import EvalRun, Feedback

STUDENT = {"HTTP_X_DEMO_TOKEN": "student-demo"}
ADMIN = {"HTTP_X_DEMO_TOKEN": "admin-demo"}


def client() -> Client:
    return Client(SERVER_NAME="localhost")


def test_feedback_requires_token():
    response = client().post(
        "/api/chat/feedback", data="{}", content_type="application/json"
    )
    assert response.status_code == 401


@pytest.mark.django_db
def test_feedback_rejects_unknown_rating():
    body = json.dumps({"question": "x", "rating": "meh"})
    response = client().post(
        "/api/chat/feedback", data=body, content_type="application/json", **STUDENT
    )
    assert response.status_code == 400
    assert "rating" in response.json()["detail"]


@pytest.mark.django_db
def test_feedback_saved_with_identity_and_trace():
    body = json.dumps(
        {
            "question": "学生证丢了怎么补办",
            "rating": "down",
            "reason": "incomplete",
            "expect": "answer",
            "answer_excerpt": "结论…",
            "conversation_id": "c-1",
        }
    )
    response = client().post(
        "/api/chat/feedback",
        data=body,
        content_type="application/json",
        HTTP_X_TRACE_ID="trace-fb-1",
        **STUDENT,
    )
    assert response.status_code == 200
    row = Feedback.objects.get(pk=response.json()["id"])
    assert row.user_key == "demo-student"          # 身份来自中间件，不接受前端伪造
    assert row.trace_id == "trace-fb-1"
    assert row.rating == Feedback.Rating.DOWN


@pytest.mark.django_db
def test_metrics_admin_only_and_shape():
    assert client().get("/api/ops/metrics", **STUDENT).status_code == 403
    body = client().get("/api/ops/metrics?days=7", **ADMIN).json()
    assert set(body) == {"days", "qa", "feedback", "evals", "golden", "env"}
    assert {"turns", "refused", "refusal_rate", "p50_ms", "p95_ms", "intents"} <= set(body["qa"])
    assert body["golden"]["samples"] >= 30          # 黄金集一直在版本库里
    assert body["env"]["main_model"]


@pytest.mark.django_db
def test_evals_listing_returns_latest_first():
    now = timezone.now()
    EvalRun.objects.create(
        kind=EvalRun.Kind.EVAL, label="old", samples=3, metrics={"hit_at_3": 1.0},
        started_at=now, finished_at=now,
    )
    EvalRun.objects.create(
        kind=EvalRun.Kind.EVAL, label="new", samples=39, metrics={"hit_at_3": 0.9},
        started_at=now, finished_at=now,
    )
    rows = client().get("/api/ops/evals", **ADMIN).json()
    assert [r["label"] for r in rows[:2]] == ["new", "old"]
    assert rows[0]["metrics"]["hit_at_3"] == 0.9


@pytest.mark.django_db
def test_feedback_listing_filters_by_rating():
    Feedback.objects.create(user_key="u", question="q1", rating=Feedback.Rating.UP)
    Feedback.objects.create(user_key="u", question="q2", rating=Feedback.Rating.DOWN)
    rows = client().get("/api/ops/feedback?rating=down", **ADMIN).json()
    assert [r["question"] for r in rows] == ["q2"]
