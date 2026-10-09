"""Task 11：服务器 CRUD API（client fixture 来自 tests/daemon/conftest.py）。"""


def test_crud_roundtrip(client):
    H = {"Authorization": "Bearer tok123"}
    assert client.get("/api/servers", headers=H).json()[0]["id"] == "l40"
    body = {"id": "s2", "name": "4090", "transport": "ssh",
            "host": "192.168.1.11", "user": "user2", "password": "pw"}
    assert client.post("/api/servers", headers=H, json=body).status_code == 200
    assert client.post("/api/servers", headers=H, json=body).status_code == 409
    body["name"] = "4090-2"
    assert client.put("/api/servers/s2", headers=H, json=body).status_code == 200
    ids = [s["id"] for s in client.get("/api/servers", headers=H).json()]
    assert "s2" in ids
    assert client.delete("/api/servers/s2", headers=H).status_code == 200
    assert client.delete("/api/servers/s2", headers=H).status_code == 404


def test_crud_put_mismatch_and_missing(client):
    H = {"Authorization": "Bearer tok123"}
    body = {"id": "s3", "name": "X", "transport": "local"}
    # PUT 路径 id 与 body id 不一致 → 400
    assert client.put("/api/servers/other", headers=H, json=body).status_code == 400
    # PUT 不存在的 id → 404
    assert client.put("/api/servers/s3", headers=H, json=body).status_code == 404


def test_crud_invalid_body(client):
    H = {"Authorization": "Bearer tok123"}
    # 非 JSON body → 422（而非 500）
    assert client.post("/api/servers", headers=H,
                       content="not json").status_code == 422
    # 非法 transport → 422（pydantic ValidationError）
    body = {"id": "s5", "name": "X", "transport": "ftp"}
    assert client.post("/api/servers", headers=H, json=body).status_code == 422
    assert client.put("/api/servers/l40", headers=H, json=body).status_code == 422


def test_crud_requires_token(client):
    body = {"id": "s9", "name": "X", "transport": "local"}
    assert client.post("/api/servers", json=body).status_code == 401
    assert client.get("/api/servers").status_code == 401
