"""HTTP API：全部端点 Bearer Token 认证。"""
import asyncio
import json
import sqlite3
import time

from fastapi import FastAPI, HTTPException, Request
from pydantic import ValidationError

from gpuviewer_daemon.config import ServerEntry


def make_app(daemon) -> FastAPI:
    app = FastAPI(title="GPUViewer Daemon", version=daemon.version)

    def _auth(request: Request):
        token = daemon.config.daemon.token
        auth = request.headers.get("authorization", "")
        if not token or auth != "Bearer " + token:
            raise HTTPException(status_code=401, detail="invalid token")

    def _exists(server_id: str) -> bool:
        return any(s.id == server_id for s in daemon.config.servers)

    async def _parse_entry(request: Request) -> ServerEntry:
        """请求体 → ServerEntry；非 JSON / 字段非法统一 422，不冒 500。

        JSONDecodeError 与 pydantic ValidationError 本身都是 ValueError 子类，
        一并列出以明示意图；TypeError 覆盖 body 为 list/null 等不可 ** 展开。
        """
        try:
            return ServerEntry(**await request.json())
        except (json.JSONDecodeError, ValidationError, ValueError, TypeError) as e:
            raise HTTPException(status_code=422, detail=str(e))

    @app.get("/api/health")
    def health(request: Request):
        _auth(request)
        return {"version": daemon.version,
                "uptime_s": round(time.time() - daemon.started_at, 1),
                "db_bytes": daemon.db_size()}

    @app.get("/api/snapshot")
    def snapshot(request: Request):
        _auth(request)
        return daemon.snapshot_payload()

    @app.get("/api/servers")
    async def list_servers(request: Request):
        _auth(request)
        return [s.model_dump() for s in daemon.config.servers]

    @app.post("/api/servers")
    async def add_server(request: Request):
        _auth(request)
        entry = await _parse_entry(request)
        if _exists(entry.id):
            raise HTTPException(status_code=409, detail="id already exists")
        await daemon.add_server(entry)
        return {"ok": True}

    @app.put("/api/servers/{server_id}")
    async def update_server(server_id: str, request: Request):
        _auth(request)
        entry = await _parse_entry(request)
        if entry.id != server_id:
            raise HTTPException(status_code=400, detail="id mismatch")
        if not _exists(server_id):
            raise HTTPException(status_code=404, detail="no such server")
        await daemon.update_server(entry)
        return {"ok": True}

    @app.delete("/api/servers/{server_id}")
    async def delete_server(server_id: str, request: Request):
        _auth(request)
        if not _exists(server_id):
            raise HTTPException(status_code=404, detail="no such server")
        await daemon.remove_server(server_id)
        return {"ok": True}

    @app.get("/api/servers/{server_id}/history")
    async def history(server_id: str, request: Request):
        _auth(request)
        if not _exists(server_id):
            raise HTTPException(status_code=404, detail="no such server")
        q = request.query_params
        if "keys" not in q or "from" not in q or "to" not in q:
            raise HTTPException(status_code=422, detail="keys/from/to required")
        try:
            t_from, t_to = float(q["from"]), float(q["to"])
            max_points = int(q.get("max_points", 500))
        except ValueError:
            raise HTTPException(status_code=422, detail="from/to/max_points must be numeric")
        key_list = [k for k in q["keys"].split(",") if k]
        try:
            # 多键大窗口查询可耗时数秒——移出事件循环，避免冻结 1s 轮询
            data = await asyncio.to_thread(
                daemon.storage.history, server_id, key_list, t_from, t_to, max_points)
        except (KeyError, ValueError, sqlite3.Error) as e:
            # KeyError: 未知 key；ValueError: gpu:0/gpu:x 等畸形 key；sqlite3.Error 兜底
            raise HTTPException(status_code=400, detail=str(e))
        return {"server_id": server_id, "keys": data}

    return app
