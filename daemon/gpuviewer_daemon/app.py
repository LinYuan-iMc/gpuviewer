"""Daemon 容器：配置/存储/调度/保留策略的组装点，API 层只依赖它。"""
import asyncio
import contextlib
import time
from pathlib import Path

from gpuviewer_daemon import __version__
from gpuviewer_daemon.config import AppConfig, ServerEntry, load_config, save_config
from gpuviewer_daemon.scheduler import Scheduler
from gpuviewer_daemon.storage import Storage


class Daemon:
    def __init__(self, config_path):
        self.config_path = Path(config_path)
        self.config: AppConfig = load_config(self.config_path)
        self.version = __version__
        self.started_at = time.time()
        self.storage: Storage | None = None
        self.scheduler: Scheduler | None = None
        self._retention_task: asyncio.Task | None = None
        self._retention_period = 3600.0          # 测试可注入更短周期

    async def start(self):
        db_path = Path(self.config.daemon.db_path)
        if not db_path.is_absolute():
            db_path = self.config_path.parent / db_path
        self.storage = Storage(db_path)
        self.scheduler = Scheduler(self)
        await self.scheduler.start()
        self._retention_task = asyncio.create_task(self._retention_loop())

    async def stop(self):
        if self._retention_task:
            self._retention_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._retention_task
            self._retention_task = None
        if self.scheduler:
            await self.scheduler.stop()
        if self.storage:
            self.storage.close()

    async def _retention_loop(self):
        while True:
            await asyncio.sleep(self._retention_period)
            # 聚合+清理扫百万行级原始表，同样不得阻塞事件循环
            await asyncio.to_thread(self.storage.aggregate_and_prune)

    def snapshot_payload(self) -> dict:
        servers = ([m.state() for m in self.scheduler.monitors.values()]
                   if self.scheduler else [])
        order = {e.id: i for i, e in enumerate(self.config.servers)}
        servers.sort(key=lambda s: order.get(s["id"], 999))
        return {"version": self.version, "servers": servers}

    def db_size(self) -> int:
        return self.storage.db_size() if self.storage else 0

    async def add_server(self, entry: ServerEntry):
        if any(s.id == entry.id for s in self.config.servers):
            raise ValueError("duplicate server id: %s" % entry.id)
        self.config.servers.append(entry)
        save_config(self.config_path, self.config)
        self.scheduler.add_server(entry)

    async def update_server(self, entry: ServerEntry):
        if not any(s.id == entry.id for s in self.config.servers):
            raise ValueError("no such server: %s" % entry.id)
        self.config.servers = [entry if s.id == entry.id else s
                               for s in self.config.servers]
        save_config(self.config_path, self.config)
        self.scheduler.remove_server(entry.id)
        self.scheduler.add_server(entry)

    async def remove_server(self, server_id: str):
        self.config.servers = [s for s in self.config.servers if s.id != server_id]
        save_config(self.config_path, self.config)
        self.scheduler.remove_server(server_id)
