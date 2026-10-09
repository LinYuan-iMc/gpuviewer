"""Task 10：API 认证 / health / snapshot。"""
import pytest


def test_requires_token(client):
    assert client.get("/api/health").status_code == 401
    assert client.get("/api/health",
                      headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_health(client):
    r = client.get("/api/health", headers={"Authorization": "Bearer tok123"})
    assert r.status_code == 200
    body = r.json()
    assert body["version"] and body["uptime_s"] >= 0 and body["db_bytes"] >= 0


def test_snapshot_shape(client):
    r = client.get("/api/snapshot", headers={"Authorization": "Bearer tok123"})
    assert r.status_code == 200
    servers = r.json()["servers"]
    assert servers[0]["id"] == "l40"
    assert servers[0]["status"] == "online"
    assert servers[0]["snapshot"]["gpus"][0]["mem_total"] == 46068


@pytest.mark.parametrize("path", ["/api/health", "/api/snapshot"])
def test_empty_token_rejects_all(client_no_token, path):
    # config token="" 时不允许任何裸访问（无头/任意 Bearer 均 401）
    assert client_no_token.get(path).status_code == 401
    assert client_no_token.get(path,
                               headers={"Authorization": "Bearer anything"}).status_code == 401
