import pytest


@pytest.mark.django_db
def test_health_returns_200_and_all_checks_ok(client):
    """P0 唯一测试：三项依赖全通时返回 200 且 ok 均为 true。"""
    resp = client.get("/api/health")
    assert resp.status_code == 200, resp.content

    body = resp.json()
    assert body["status"] == "ok"
    assert body["version"]
    for name in ("db", "redis", "storage"):
        assert body["checks"][name]["ok"] is True, f"{name} 未通过：{body['checks'][name]}"
