import asyncio
from pathlib import Path

import pytest
from gpuviewer_daemon.app import Daemon
from gpuviewer_daemon.config import ServerEntry


def write_cfg(tmp_path: Path) -> Path:
    p = tmp_path / "config.toml"
    p.write_text("""[daemon]
token = "t"
db_path = "{db}"
interval_s = 0.05

[[servers]]
id = "l40"
name = "L40"
transport = "local"
enabled = true
""".replace("{db}", str(tmp_path / "d.db")).replace("\\", "/"), encoding="utf-8")
    return p


async def test_daemon_collects_local_and_crud(tmp_path, monkeypatch, make_snapshot):
    cfg_path = write_cfg(tmp_path)
    import gpuviewer_daemon.scheduler as sched_mod

    class FakeRunner:
        def __init__(self):
            self.snap = make_snapshot()

        async def run(self, timeout=10.0):
            return self.snap

        async def close(self):
            pass

    # Scheduler 会以 make_runner(entry, accept_host_keys=...) 透传配置
    monkeypatch.setattr(sched_mod, "make_runner", lambda e, **kw: FakeRunner())
    d = Daemon(cfg_path)
    await d.start()
    await asyncio.sleep(0.3)
    payload = d.snapshot_payload()
    assert payload["version"] == d.version
    assert payload["servers"][0]["status"] == "online"
    assert payload["servers"][0]["snapshot"]["cpu"]["cores"] == 2

    # CRUD：新增一台（假 runner），写回配置文件
    new_entry = ServerEntry(id="x2", name="X2", transport="local")
    await d.add_server(new_entry)
    ids = [s["id"] for s in d.snapshot_payload()["servers"]]
    assert "x2" in ids
    from gpuviewer_daemon.config import load_config
    assert "x2" in [s.id for s in load_config(cfg_path).servers]
    await d.remove_server("x2")
    assert "x2" not in [s["id"] for s in d.snapshot_payload()["servers"]]
    await d.stop()


async def test_daemon_crud_rejects_duplicate_and_missing_id(tmp_path, monkeypatch, make_snapshot):
    cfg_path = write_cfg(tmp_path)
    import gpuviewer_daemon.scheduler as sched_mod

    class FakeRunner:
        def __init__(self):
            self.snap = make_snapshot()

        async def run(self, timeout=10.0):
            return self.snap

        async def close(self):
            pass

    monkeypatch.setattr(sched_mod, "make_runner", lambda e, **kw: FakeRunner())
    d = Daemon(cfg_path)
    await d.start()
    try:
        # 重复 add：抛 ValueError，config 不变
        dup = ServerEntry(id="l40", name="dup", transport="local")
        with pytest.raises(ValueError, match="duplicate server id"):
            await d.add_server(dup)
        assert [s.id for s in d.config.servers] == ["l40"]

        # update 不存在的 id：抛 ValueError，调度器不 spawn
        ghost = ServerEntry(id="ghost", name="ghost", transport="local")
        with pytest.raises(ValueError, match="no such server"):
            await d.update_server(ghost)
        assert "ghost" not in d.scheduler.monitors
        assert [s.id for s in d.config.servers] == ["l40"]
    finally:
        await d.stop()


async def test_scheduler_wires_top_n_to_runner(tmp_path, monkeypatch, make_snapshot):
    """I-2：config 的 top_n 必须传入 runner 与 monitor（不再死配置）。"""
    p = tmp_path / "config.toml"
    p.write_text("""[daemon]
token = "t"
db_path = "{db}"
interval_s = 0.05
top_n = 3

[[servers]]
id = "l40"
name = "L40"
transport = "local"
""".replace("{db}", str(tmp_path / "d.db").replace("\\", "/"), 1).replace("\\", "/"),
                  encoding="utf-8")
    import gpuviewer_daemon.scheduler as sched_mod

    class FakeRunner:
        async def run(self, timeout=10.0):
            return make_snapshot()

        async def close(self):
            pass

    captured = {}

    def fake_make(e, **kw):
        captured.update(kw)
        return FakeRunner()

    monkeypatch.setattr(sched_mod, "make_runner", fake_make)
    d = Daemon(p)
    await d.start()
    try:
        assert captured.get("top_n") == 3                  # config → make_runner
        assert d.scheduler.monitors["l40"].top_n == 3     # config → ServerMonitor
    finally:
        await d.stop()


@pytest.mark.asyncio
async def test_deadline_scheduling():
    """截止时间制：探针耗时应从睡眠中扣除（周期≈interval 而非 interval+探针）。"""
    import time as _t

    from gpuviewer_daemon.scheduler import ServerMonitor

    class SlowRunner:
        async def run(self, timeout=10.0):
            await asyncio.sleep(0.2)              # 模拟探针耗时 0.2s
            return {"ts": _t.time(), "errors": [], "gpus": [], "net": [],
                    "disks": [], "cpu": {}, "memory": {}, "host": {},
                    "gpu_processes": [], "top_cpu": [], "top_mem": []}

        async def close(self):
            pass

    class Store:
        def write_snapshot(self, *a, **k):
            pass

    class E:
        id, name, transport = "x", "X", "local"

    m = ServerMonitor(E(), Store(), runner=SlowRunner(), interval_s=0.3)
    task = asyncio.create_task(m.run_forever())
    t0 = _t.monotonic()
    await asyncio.sleep(1.0)                      # ~3 个周期
    m._stop = True
    m._sleep_event().set()
    await asyncio.sleep(0.4)
    task.cancel()
    elapsed = _t.monotonic() - t0 - 0.4
    # 旧逻辑：周期 0.5s → 1.0s 内仅 2 轮；新逻辑：周期 0.3s → 3 轮。
    # 用轮次计时刻度太脆，改用宽上界：3 轮×0.3s=0.9s，若仍是旧逻辑会 >1.2s
    assert elapsed < 1.35, "调度未按截止时间制运转（疑似退化为 interval+探针串行叠加）"
