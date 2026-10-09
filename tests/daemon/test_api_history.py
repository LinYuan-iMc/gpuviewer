"""Task 12：历史查询 API（from/to 为查询参数名，避免 Python 关键字）。"""
import pytest


def test_history(client):
    H = {"Authorization": "Bearer tok123"}
    r = client.get("/api/servers/l40/history",
                   params={"keys": "cpu_total,gpu:0.util", "from": 0, "to": 99999999999,
                           "max_points": 100}, headers=H)
    assert r.status_code == 200
    body = r.json()
    assert body["server_id"] == "l40"
    assert body["keys"]["cpu_total"][0][1] == 12.5
    assert body["keys"]["gpu:0.util"][0][1] == 87.0


def test_history_errors(client):
    H = {"Authorization": "Bearer tok123"}
    assert client.get("/api/servers/none/history",
                      params={"keys": "cpu_total", "from": 0, "to": 1},
                      headers=H).status_code == 404
    assert client.get("/api/servers/l40/history",
                      params={"keys": "bogus", "from": 0, "to": 1},
                      headers=H).status_code == 400


@pytest.mark.parametrize("bad_key", ["gpu:0", "gpu:x.util", "net:eth0.bogus"])
def test_history_malformed_key(client, bad_key):
    # gpu:0 缺字段→ValueError；gpu:x.util int() 失败→ValueError；
    # net:eth0.bogus 未白名单字段→KeyError（修复前为 SQL 拼接 OperationalError）
    H = {"Authorization": "Bearer tok123"}
    assert client.get("/api/servers/l40/history",
                      params={"keys": bad_key, "from": 0, "to": 1},
                      headers=H).status_code == 400


def test_history_non_numeric_range(client):
    H = {"Authorization": "Bearer tok123"}
    assert client.get("/api/servers/l40/history",
                      params={"keys": "cpu_total", "from": "abc", "to": 1},
                      headers=H).status_code == 422
    assert client.get("/api/servers/l40/history",
                      params={"keys": "cpu_total", "from": 0, "to": 1,
                              "max_points": "x"},
                      headers=H).status_code == 422


def test_history_missing_params(client):
    H = {"Authorization": "Bearer tok123"}
    # 缺 keys/from/to 任意一项 → 422
    assert client.get("/api/servers/l40/history", headers=H).status_code == 422
    assert client.get("/api/servers/l40/history", params={"keys": "cpu_total"},
                      headers=H).status_code == 422
    assert client.get("/api/servers/l40/history",
                      params={"keys": "cpu_total", "from": 0},
                      headers=H).status_code == 422
