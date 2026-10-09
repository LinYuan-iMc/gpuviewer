import asyncio

import pytest
from gpuviewer_daemon.config import ServerEntry
from gpuviewer_daemon.scheduler import ServerMonitor
from gpuviewer_daemon.storage import Storage


class FakeRunner:
    def __init__(self, results):
        self._results = list(results)
        self.calls = 0

    async def run(self, timeout=10.0):
        self.calls += 1
        r = self._results.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    async def close(self):
        pass


@pytest.fixture
def storage(tmp_path):
    s = Storage(tmp_path / "m.db")
    yield s
    s.close()


def entry():
    return ServerEntry(id="l40", name="L40", transport="local")


async def test_poll_success_online(storage, make_snapshot):
    m = ServerMonitor(entry(), storage, runner=FakeRunner([make_snapshot()]))
    assert await m.poll_once() is True
    assert m.state()["status"] == "online"
    assert m.state()["snapshot"]["gpus"][0]["name"] == "NVIDIA L40"
    hist = storage.history("l40", ["cpu_total"], 0, 99999999999)
    assert hist["cpu_total"]


async def test_poll_failure_offline_keeps_last(storage, make_snapshot):
    m = ServerMonitor(entry(), storage,
                      runner=FakeRunner([make_snapshot(), RuntimeError("ssh down")]))
    await m.poll_once()
    assert await m.poll_once() is False
    assert m.state()["status"] == "offline"
    assert "ssh down" in m.state()["last_error"]
    assert m.state()["snapshot"] is not None          # 保留最后成功快照
    assert m.state()["last_success_ts"] == pytest.approx(make_snapshot()["ts"])


async def test_degraded_on_probe_errors(storage, make_snapshot):
    snap = make_snapshot(errors=["read_gpus: boom"])
    m = ServerMonitor(entry(), storage, runner=FakeRunner([snap]))
    await m.poll_once()
    assert m.state()["status"] == "degraded"


async def test_net_rate_diff(storage, make_snapshot):
    s1, s2 = make_snapshot(), make_snapshot()
    s2["ts"] = s1["ts"] + 5
    s1["net"] = [{"name": "eth0", "rx_bytes": 1000, "tx_bytes": 500}]
    s2["net"] = [{"name": "eth0", "rx_bytes": 6000, "tx_bytes": 2500}]
    m = ServerMonitor(entry(), storage, runner=FakeRunner([s1, s2]))
    await m.poll_once()
    await m.poll_once()
    hist = storage.history("l40", ["net:eth0.rx", "net:eth0.tx"], 0, 99999999999)
    assert hist["net:eth0.rx"][-1][1] == pytest.approx(1000.0)   # (6000-1000)/5
    assert hist["net:eth0.tx"][-1][1] == pytest.approx(400.0)
    # 差分速率写回快照：客户端详情页直接读 rx_rate/tx_rate
    assert m.state()["snapshot"]["net"][0]["rx_rate"] == 1000.0
    assert m.state()["snapshot"]["net"][0]["tx_rate"] == 400.0


async def test_run_forever_backoff(storage, make_snapshot):
    runner = FakeRunner([RuntimeError("x")] * 3 + [make_snapshot()])
    m = ServerMonitor(entry(), storage, runner=runner, interval_s=0.01, backoff_base=0.02)
    task = asyncio.create_task(m.run_forever())
    for _ in range(200):
        if runner.calls >= 4:
            break
        await asyncio.sleep(0.01)
    await m.stop()
    await asyncio.wait_for(task, 2)
    assert m.state()["status"] == "online"
