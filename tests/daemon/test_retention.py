from pathlib import Path

import pytest
from gpuviewer_daemon.storage import Storage


def test_aggregate_and_prune_multi_server(tmp_path: Path, make_snapshot):
    s = Storage(tmp_path / "t.db")
    try:
        now = 2_000_000.0
        for srv in ("a", "b"):
            for i in range(5):
                snap = make_snapshot()
                snap["ts"] = now - 60 * 3600 - i * 5
                snap["cpu"]["utilization_total"] = 50.0
                s.write_snapshot(srv, snap, {"eth0": (1.0, 2.0)})
        s.aggregate_and_prune(now)
        for srv in ("a", "b"):
            raw_old = s._db.execute(
                "SELECT COUNT(*) FROM samples WHERE server_id = ? AND ts < ?",
                (srv, now - 48 * 3600)).fetchone()[0]
            agg = s._db.execute(
                "SELECT COUNT(*) FROM samples_agg WHERE server_id = ?", (srv,)).fetchone()[0]
            net_agg = s._db.execute(
                "SELECT COUNT(*) FROM net_samples_agg WHERE server_id = ?",
                (srv,)).fetchone()[0]
            assert raw_old == 0
            assert agg >= 1
            assert net_agg >= 1
    finally:
        s.close()


def test_aggregate_and_prune(tmp_path: Path, make_snapshot):
    s = Storage(tmp_path / "t.db")
    try:
        now = 2_000_000.0
        for i in range(10):                        # 60h 前 → 应被聚合+删除
            snap = make_snapshot()
            snap["ts"] = now - 60 * 3600 - i * 5
            snap["cpu"]["utilization_total"] = 50.0
            s.write_snapshot("srv", snap, {})
        for i in range(10):                        # 1h 前 → 保留原始
            snap = make_snapshot()
            snap["ts"] = now - 3600 - i * 5
            snap["cpu"]["utilization_total"] = 10.0
            s.write_snapshot("srv", snap, {})
        s.aggregate_and_prune(now)
        raw_old = s._db.execute(
            "SELECT COUNT(*) FROM samples WHERE ts < ?", (now - 48 * 3600,)).fetchone()[0]
        agg = s._db.execute("SELECT COUNT(*) FROM samples_agg").fetchone()[0]
        assert raw_old == 0
        assert agg >= 1
        # 聚合行可被 history 查询（走 raw+agg 合并）
        hist = s.history("srv", ["cpu_total"], now - 61 * 3600, now - 59 * 3600)
        assert hist["cpu_total"] and hist["cpu_total"][0][1] == pytest.approx(50.0)
        # 幂等：重复执行不产生重复聚合
        s.aggregate_and_prune(now)
        agg2 = s._db.execute("SELECT COUNT(*) FROM samples_agg").fetchone()[0]
        assert agg2 == agg
        # 30 天前的聚合行被清理
        s._db.execute("INSERT INTO samples_agg SELECT * FROM samples LIMIT 1")
        s._db.execute("UPDATE samples_agg SET ts = ?", (now - 31 * 86400,))
        s.aggregate_and_prune(now)
        old = s._db.execute(
            "SELECT COUNT(*) FROM samples_agg WHERE ts < ?", (now - 30 * 86400,)).fetchone()[0]
        assert old == 0
    finally:
        s.close()
