"""限流：分桶、计数、429 与 Retry-After。"""

import pytest
from django.test import Client

from apps.access import limit
from apps.access.models import ApiLog

STUDENT = {"HTTP_X_DEMO_TOKEN": "student-demo"}


@pytest.fixture(autouse=True)
def _clear_buckets():
    """限流键在 Redis 里按分钟累计，用例之间必须清，否则第二次跑就撞满。"""
    from django.core.cache import cache

    def _drop():
        # django-redis 会给键加库前缀（:1:acc:rl:…），按前缀删不准，直接扫一遍
        client = cache.client.get_client(write=True)
        for key in client.scan_iter(match="*acc:rl:*"):
            client.delete(key)

    _drop()
    yield
    _drop()


def client() -> Client:
    return Client(SERVER_NAME="localhost")


def post_stream(c: Client):
    """不真调模型：空 payload 会先撞参数校验，但限流计数已经发生。"""
    return c.post("/api/chat/stream", data="{}", content_type="application/json", **STUDENT)


@pytest.mark.django_db
def test_chat_bucket_rejects_after_limit(settings):
    settings.ACCESS_RATE_CHAT = 2
    c = client()
    codes = []
    for _ in range(3):
        # 不真的调模型：撞限流的那次在第 3 次，前两次走到 401/400 也算计数
        codes.append(post_stream(c).status_code)
    assert codes[0] != 429 and codes[1] != 429
    assert codes[2] == 429


@pytest.mark.django_db
def test_rate_limit_response_has_retry_after(settings):
    settings.ACCESS_RATE_CHAT = 1
    c = client()
    post_stream(c)
    blocked = post_stream(c)
    assert blocked.status_code == 429
    assert 1 <= int(blocked["Retry-After"]) <= 60
    assert blocked["X-RateLimit-Remaining"] == "0"
    assert ApiLog.objects.filter(limited=True, path="/api/chat/stream").exists()


@pytest.mark.django_db
def test_buckets_are_independent(settings):
    settings.ACCESS_RATE_CHAT = 1
    settings.ACCESS_RATE_READ = 5
    c = client()
    post_stream(c)
    assert post_stream(c).status_code == 429
    # 聊天桶打满不影响读接口
    assert c.get("/api/chat/me", **STUDENT).status_code == 200


def test_bucket_routing():
    assert limit.bucket_of("POST", "/api/chat/stream") == limit.CHAT
    assert limit.bucket_of("POST", "/api/chat/turn") == limit.CHAT
    assert limit.bucket_of("POST", "/api/ops/uploads") == limit.WRITE
    assert limit.bucket_of("GET", "/api/ops/dashboard") == limit.READ
    assert limit.bucket_of("GET", "/api/chat/sessions") == limit.READ
