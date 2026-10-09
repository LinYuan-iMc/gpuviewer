"""SQLite(WAL) 时序存储：写入快照标量、历史桶聚合查询、保留策略。"""
import sqlite3
import threading
import time
from pathlib import Path

_STATIC = {"cpu_total": "cpu_total", "load1": "load1", "load5": "load5", "load15": "load15",
           "mem_total": "mem_total", "mem_used": "mem_used", "mem_avail": "mem_avail",
           "swap_used": "swap_used"}
_GPU_FIELDS = {"util": "util", "mem_util": "mem_util", "mem_used": "mem_used",
               "mem_total": "mem_total", "temp": "temp", "power_draw": "power_draw",
               "power_limit": "power_limit", "fan": "fan"}
_NET_FIELDS = {"rx": "rx", "tx": "tx"}
_DISK_FIELDS = {"pct": "pct", "used": "used", "total": "total", "avail": "avail"}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS samples(
  server_id TEXT NOT NULL, ts REAL NOT NULL,
  cpu_total REAL, load1 REAL, load5 REAL, load15 REAL,
  mem_total INTEGER, mem_used INTEGER, mem_avail INTEGER,
  swap_total INTEGER, swap_used INTEGER, uptime_s REAL);
CREATE INDEX IF NOT EXISTS ix_samples ON samples(server_id, ts);
CREATE TABLE IF NOT EXISTS gpu_samples(
  server_id TEXT NOT NULL, ts REAL NOT NULL, gpu_index INTEGER NOT NULL,
  util REAL, mem_util REAL, mem_used REAL, mem_total REAL,
  temp REAL, power_draw REAL, power_limit REAL, fan REAL);
CREATE INDEX IF NOT EXISTS ix_gpu ON gpu_samples(server_id, gpu_index, ts);
CREATE TABLE IF NOT EXISTS net_samples(
  server_id TEXT NOT NULL, ts REAL NOT NULL, iface TEXT NOT NULL, rx REAL, tx REAL);
CREATE INDEX IF NOT EXISTS ix_net ON net_samples(server_id, iface, ts);
CREATE TABLE IF NOT EXISTS disk_samples(
  server_id TEXT NOT NULL, ts REAL NOT NULL, mount TEXT NOT NULL,
  used INTEGER, total INTEGER, avail INTEGER, pct REAL);
CREATE INDEX IF NOT EXISTS ix_disk ON disk_samples(server_id, mount, ts);
"""


def _agg_schema() -> str:
    """聚合表与原表同构，表名加 _agg 后缀；索引名加 ix_agg_ 前缀避免与原表索引同名被跳过。"""
    return _SCHEMA.replace("ix_", "ix_agg_").replace("samples", "samples_agg")


_AGG_SPECS = [
    ("samples", "samples_agg",
     "INSERT INTO {agg} SELECT server_id, CAST(ts/60 AS INTEGER)*60, AVG(cpu_total), "
     "AVG(load1), AVG(load5), AVG(load15), AVG(mem_total), AVG(mem_used), "
     "AVG(mem_avail), AVG(swap_total), AVG(swap_used), AVG(uptime_s) "
     "FROM {raw} WHERE server_id = ? AND ts > ? AND ts < ? GROUP BY server_id, 2"),
    ("gpu_samples", "gpu_samples_agg",
     "INSERT INTO {agg} SELECT server_id, CAST(ts/60 AS INTEGER)*60, gpu_index, AVG(util), "
     "AVG(mem_util), AVG(mem_used), AVG(mem_total), AVG(temp), AVG(power_draw), "
     "AVG(power_limit), AVG(fan) FROM {raw} WHERE server_id = ? AND ts > ? AND ts < ? "
     "GROUP BY server_id, 2, gpu_index"),
    ("net_samples", "net_samples_agg",
     "INSERT INTO {agg} SELECT server_id, CAST(ts/60 AS INTEGER)*60, iface, AVG(rx), "
     "AVG(tx) FROM {raw} WHERE server_id = ? AND ts > ? AND ts < ? GROUP BY server_id, 2, iface"),
    ("disk_samples", "disk_samples_agg",
     "INSERT INTO {agg} SELECT server_id, CAST(ts/60 AS INTEGER)*60, mount, AVG(used), "
     "AVG(total), AVG(avail), AVG(pct) FROM {raw} WHERE server_id = ? AND ts > ? AND ts < ? "
     "GROUP BY server_id, 2, mount"),
]


class Storage:
    def __init__(self, path: Path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(_SCHEMA)
        self._db.executescript(_agg_schema())
        self._db.commit()
        self.path = path
        # history 查询移入线程后（api 层 asyncio.to_thread），同一条连接会被
        # 事件循环与工作线程并发使用——串行化全部库访问。
        self._lock = threading.Lock()

    # ---------- 写入 ----------
    def write_snapshot(self, server_id: str, snap: dict,
                       net_rates: dict | None = None) -> None:
        net_rates = net_rates or {}
        with self._lock:
            return self._write_snapshot_impl(server_id, snap, net_rates)

    def _write_snapshot_impl(self, server_id: str, snap: dict,
                             net_rates: dict | None = None) -> None:
        net_rates = net_rates or {}
        ts = snap["ts"]
        cpu, mem = snap.get("cpu", {}), snap.get("memory", {})
        host = snap.get("host", {})
        self._db.execute(
            "INSERT INTO samples VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (server_id, ts, cpu.get("utilization_total"), cpu.get("load1"),
             cpu.get("load5"), cpu.get("load15"), mem.get("total"), mem.get("used"),
             mem.get("available"), mem.get("swap_total"), mem.get("swap_used"),
             host.get("uptime_s")))
        for g in snap.get("gpus", []):
            self._db.execute(
                "INSERT INTO gpu_samples VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (server_id, ts, g.get("index"), g.get("utilization"),
                 g.get("mem_utilization"), g.get("mem_used"), g.get("mem_total"),
                 g.get("temperature"), g.get("power_draw"), g.get("power_limit"),
                 g.get("fan_speed")))
        for iface, (rx, tx) in net_rates.items():
            self._db.execute("INSERT INTO net_samples VALUES (?,?,?,?,?)",
                             (server_id, ts, iface, rx, tx))
        for d in snap.get("disks", []):
            self._db.execute("INSERT INTO disk_samples VALUES (?,?,?,?,?,?,?)",
                             (server_id, ts, d.get("mount"), d.get("used"),
                              d.get("total"), d.get("avail"), d.get("pct")))
        self._db.commit()

    # ---------- 查询 ----------
    def _route(self, key: str):
        if key in _STATIC:
            return "samples", _STATIC[key], "", []
        if key.startswith("gpu:"):
            rest = key[len("gpu:"):]
            idx, field = rest.split(".", 1)
            return "gpu_samples", _GPU_FIELDS[field], " AND gpu_index = ?", [int(idx)]
        if key.startswith("net:"):
            rest = key[len("net:"):]
            iface, field = rest.split(".", 1)
            return "net_samples", _NET_FIELDS[field], " AND iface = ?", [iface]
        if key.startswith("disk:"):
            rest = key[len("disk:"):]
            mount, field = rest.rsplit(".", 1)
            return "disk_samples", _DISK_FIELDS[field], " AND mount = ?", [mount]
        raise KeyError("unknown history key: %s" % key)

    def history(self, server_id: str, keys: list[str], t_from: float, t_to: float,
                max_points: int = 500) -> dict[str, list[list[float]]]:
        # 整段不加锁：_history_impl 每条 SQL 单独持锁——大查询期间写库可穿插，
        # 采集不中断（持有大锁会让事件循环上的写方阻塞冻结整个服务）。
        return self._history_impl(server_id, keys, t_from, t_to, max_points)

    def _history_impl(self, server_id: str, keys: list[str], t_from: float,
                      t_to: float, max_points: int = 500) -> dict[str, list[list[float]]]:
        out: dict[str, list[list[float]]] = {}
        span = max(t_to - t_from, 1.0)
        bucket = max(1.0, span / max(max_points, 1))
        for key in keys:
            table, col, extra_sql, extra_args = self._route(key)
            merged: dict[float, float] = {}
            # 先 agg 后 raw 才能让 raw 覆盖同桶聚合值
            for t in (table + "_agg", table):
                sql = (f"SELECT CAST(ts / {bucket} AS INTEGER) * {bucket} AS b, AVG({col}) "
                       f"FROM {t} WHERE server_id = ? AND ts BETWEEN ? AND ?{extra_sql} "
                       "GROUP BY b ORDER BY b")
                with self._lock:
                    rows = self._db.execute(sql, [server_id, t_from, t_to] + extra_args).fetchall()
                for b, v in rows:                        # 原始表后查，覆盖聚合桶
                    if v is not None:
                        merged[float(b)] = float(v)
            out[key] = [[b, v] for b, v in sorted(merged.items())]
        return out

    # ---------- 保留策略 ----------
    def _watermark(self, key: str) -> float:
        row = self._db.execute("SELECT value FROM meta WHERE k = ?", (key,)).fetchone()
        return row[0] if row else 0.0

    def aggregate_and_prune(self, now: float | None = None) -> None:
        with self._lock:
            self._aggregate_and_prune_impl(now)

    def _aggregate_and_prune_impl(self, now: float | None = None) -> None:
        now = now if now is not None else time.time()
        self._db.execute("CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, value REAL)")
        raw_cutoff = now - 48 * 3600
        agg_cutoff = now - 30 * 86400
        servers = [r[0] for r in self._db.execute(
            "SELECT DISTINCT server_id FROM samples").fetchall()]
        for raw_table, agg_table, tmpl in _AGG_SPECS:
            for srv in servers:
                wm_key = f"agg_wm_{raw_table}:{srv}"     # 每表每 server 一条水位线
                wm = self._watermark(wm_key)
                sql = tmpl.format(raw=raw_table, agg=agg_table)
                self._db.execute(sql, (srv, wm, raw_cutoff))
                self._db.execute(
                    "INSERT OR REPLACE INTO meta VALUES (?, ?)", (wm_key, raw_cutoff))
            self._db.execute(f"DELETE FROM {raw_table} WHERE ts < ?", (raw_cutoff,))
            self._db.execute(f"DELETE FROM {agg_table} WHERE ts < ?", (agg_cutoff,))
        self._db.commit()

    def db_size(self) -> int:
        for suffix in ("", "-wal", "-shm"):
            p = Path(str(self.path) + suffix)
            if p.exists():
                return p.stat().st_size
        return 0

    def close(self):
        # 持锁关闭：工作线程可能正在执行语句（to_thread 写库/查询），
        # 无锁并发 close 是 C 层 use-after-close 访问违例。
        with self._lock:
            self._db.close()
