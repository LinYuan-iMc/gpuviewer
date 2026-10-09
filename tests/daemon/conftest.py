"""Daemon API 测试共享 fixture：临时配置 + FakeRunner + 已启动采集的 TestClient。

pytest-asyncio 1.4.0 已移除 event_loop fixture，且 TestClient 的 lifespan
不触发 Daemon.start()——故用 asyncio.run() 包裹 start/stop：首轮采集在
setup 的 0.05s 窗口内完成（内存 state 与 DB 均已写入），随后 loop 关闭
仅取消 monitor task；TestClient 线程访问 state()/history 为纯内存/SQLite
读取，不受影响。
"""
import asyncio
import contextlib

import pytest
from fastapi.testclient import TestClient
from gpuviewer_daemon.api import make_app
from gpuviewer_daemon.app import Daemon


@contextlib.contextmanager
def _api_client(tmp_path, monkeypatch, make_snapshot, token: str):
    p = tmp_path / "config.toml"
    p.write_text(f"""[daemon]
token = "{token}"
db_path = "{str(tmp_path / 'd.db').replace(chr(92), '/')}"

[[servers]]
id = "l40"
name = "L40"
transport = "local"
""", encoding="utf-8")
    import gpuviewer_daemon.scheduler as sched_mod

    class FakeRunner:
        async def run(self, timeout=10.0):
            return make_snapshot()

        async def close(self):
            pass

    # 必须在 daemon.start() 前生效（Scheduler._spawn 以 make_runner(entry, accept_host_keys=...) 调用）
    monkeypatch.setattr(sched_mod, "make_runner", lambda e, **kw: FakeRunner())
    daemon = Daemon(p)
    daemon._retention_period = 99999

    async def _setup():
        await daemon.start()
        await asyncio.sleep(0.05)   # 首轮探针→写库→state=online

    asyncio.run(_setup())
    app = make_app(daemon)
    with TestClient(app) as c:
        yield c
    asyncio.run(daemon.stop())


@pytest.fixture
def client(tmp_path, monkeypatch, make_snapshot):
    with _api_client(tmp_path, monkeypatch, make_snapshot, token="tok123") as c:
        yield c


@pytest.fixture
def client_no_token(tmp_path, monkeypatch, make_snapshot):
    """token 为空的配置：所有端点必须一律 401（不可裸奔）。"""
    with _api_client(tmp_path, monkeypatch, make_snapshot, token="") as c:
        yield c
