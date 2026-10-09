"""每服务器一个监控任务：探针→差分→写库→状态机；失败指数退避。"""
import asyncio
import contextlib
import time

from gpuviewer_daemon.config import ServerEntry
from gpuviewer_daemon.probe.runner import make_runner
from gpuviewer_daemon.storage import Storage


def _net_rates(prev_snap: dict | None, snap: dict) -> dict[str, tuple[float, float]]:
    if not prev_snap:
        return {}
    dt = snap["ts"] - prev_snap.get("ts", 0)
    if dt <= 0:
        return {}
    prev = {i["name"]: (i["rx_bytes"], i["tx_bytes"]) for i in prev_snap.get("net", [])}
    out = {}
    for i in snap.get("net", []):
        if i["name"] in prev:
            prx, ptx = prev[i["name"]]
            out[i["name"]] = (max(0.0, (i["rx_bytes"] - prx) / dt),
                              max(0.0, (i["tx_bytes"] - ptx) / dt))
    return out


class ServerMonitor:
    def __init__(self, entry: ServerEntry, storage: Storage, interval_s: float = 5.0,
                 timeout_s: float = 10.0, runner=None, backoff_base: float = 5.0,
                 top_n: int = 10):
        self.entry = entry
        self.storage = storage
        self.interval_s = interval_s
        self.timeout_s = timeout_s
        self.backoff_base = backoff_base
        self.top_n = top_n
        self.runner = runner if runner is not None else make_runner(entry, top_n=top_n)
        self._prev: dict | None = None
        self._last_snap: dict | None = None
        self._last_ok_ts: float | None = None
        self._status = "offline"
        self._last_error: str | None = None
        self._stop = False

    def state(self) -> dict:
        return {"id": self.entry.id, "name": self.entry.name,
                "status": self._status, "last_error": self._last_error,
                "last_success_ts": self._last_ok_ts, "snapshot": self._last_snap}

    async def poll_once(self) -> bool:
        try:
            snap = await self.runner.run(timeout=self.timeout_s)
        except Exception as e:     # ProbeError/asyncio.TimeoutError 均为其子集
            self._status = "offline"
            self._last_error = str(e)
            return False
        rates = _net_rates(self._prev, snap)
        # 差分速率写回快照：API/客户端直接读 net[i]["rx_rate"/"tx_rate"]
        for i in snap.get("net", []):
            if i["name"] in rates:
                i["rx_rate"], i["tx_rate"] = rates[i["name"]]
        try:
            # 写库走工作线程：storage 锁可能被大历史查询持有数秒，
            # 在协程里同步抢锁会冻结整个事件循环。
            await asyncio.to_thread(self.storage.write_snapshot,
                                    self.entry.id, snap, rates)
        except Exception as e:                          # noqa: BLE001
            self._status = "offline"
            self._last_error = "storage: %s" % e
            return False
        self._status = "degraded" if snap.get("errors") else "online"
        self._last_error = "; ".join(snap["errors"]) if snap.get("errors") else None
        self._prev, self._last_snap, self._last_ok_ts = snap, snap, snap["ts"]
        return True

    async def run_forever(self):
        fails = 0
        while not self._stop:
            t0 = time.monotonic()
            ok = await self.poll_once()
            elapsed = time.monotonic() - t0
            fails = 0 if ok else fails + 1
            # 截止时间制：周期=间隔——探针耗时从睡眠中扣除（超时则背靠背采集），
            # 否则"跑完再睡满 N 秒"会让实际节奏 = N+探针时长，永远达不到设定值。
            delay = (max(0.05, self.interval_s - elapsed) if ok else
                     min(60.0, self.backoff_base * (2 ** min(fails - 1, 10))))
            try:
                await asyncio.wait_for(self._sleep_event().wait(), delay)
            except asyncio.TimeoutError:
                pass

    def _sleep_event(self):
        if not hasattr(self, "_wake"):
            self._wake = asyncio.Event()
        return self._wake

    async def stop(self):
        self._stop = True
        self._sleep_event().set()
        await self.runner.close()


class Scheduler:
    """错峰启动各 ServerMonitor，并支持运行时增删（监控注册同步生效）。"""

    def __init__(self, daemon):
        self._daemon = daemon
        self.monitors: dict[str, ServerMonitor] = {}
        self._tasks: dict[str, asyncio.Task] = {}

    async def start(self):
        entries = [e for e in self._daemon.config.servers if e.enabled]
        n = max(len(entries), 1)
        for i, e in enumerate(entries):
            self._spawn(e, stagger=i * self._daemon.config.daemon.interval_s / n)

    def _spawn(self, entry: ServerEntry, stagger: float = 0.0):
        # 同步注册 monitor（add_server 后立即对 snapshot_payload 可见），任务体仅做错峰+循环
        runner = make_runner(entry,
                             accept_host_keys=self._daemon.config.daemon.accept_host_keys,
                             top_n=self._daemon.config.daemon.top_n)
        m = ServerMonitor(entry, self._daemon.storage, runner=runner,
                          interval_s=self._daemon.config.daemon.interval_s,
                          timeout_s=self._daemon.config.daemon.probe_timeout_s,
                          top_n=self._daemon.config.daemon.top_n)
        self.monitors[entry.id] = m

        async def _run():
            if stagger:
                await asyncio.sleep(stagger)
            await m.run_forever()

        self._tasks[entry.id] = asyncio.create_task(_run())

    def add_server(self, entry: ServerEntry):
        self._spawn(entry)

    def remove_server(self, server_id: str):
        m = self.monitors.pop(server_id, None)
        t = self._tasks.pop(server_id, None)
        if t:
            t.cancel()
        if m:
            asyncio.create_task(m.stop())

    async def stop(self):
        for t in self._tasks.values():
            t.cancel()
        for m in self.monitors.values():
            await m.stop()
        for t in self._tasks.values():
            with contextlib.suppress(asyncio.CancelledError):
                await t
        self._tasks.clear()
        self.monitors.clear()
