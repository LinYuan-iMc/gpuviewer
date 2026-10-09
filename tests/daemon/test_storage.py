from pathlib import Path

import pytest
from gpuviewer_daemon.storage import Storage


@pytest.fixture
def store(tmp_path: Path):
    s = Storage(tmp_path / "t.db")
    yield s
    s.close()


def test_write_and_history_cpu(store, make_snapshot):
    snap = make_snapshot()
    snap["cpu"]["utilization_total"] = 11.0
    store.write_snapshot("l40", snap, {"eth0": (1024.0, 2048.0)})
    snap2 = make_snapshot()
    snap2["ts"] = snap["ts"] + 5
    snap2["cpu"]["utilization_total"] = 33.0
    store.write_snapshot("l40", snap2, {"eth0": (1024.0, 2048.0)})
    hist = store.history("l40", ["cpu_total", "mem_used"], snap["ts"] - 1, snap2["ts"] + 1)
    assert [v for _, v in hist["cpu_total"]] == [11.0, 33.0]
    assert hist["mem_used"][0][1] == snap["memory"]["used"]


def test_history_gpu_net_disk_keys(store, make_snapshot):
    snap = make_snapshot()
    store.write_snapshot("s", snap, {"eth0": (10.0, 20.0)})
    hist = store.history("s", ["gpu:0.util", "net:eth0.rx", "disk:/.pct"],
                         snap["ts"] - 1, snap["ts"] + 1)
    assert hist["gpu:0.util"][0][1] == 87.0
    assert hist["net:eth0.rx"][0][1] == 10.0
    assert hist["disk:/.pct"][0][1] == 70.0


def test_history_downsamples(store, make_snapshot):
    for i in range(100):
        snap2 = make_snapshot()
        snap2["ts"] = 1_000_000 + i * 10
        snap2["cpu"]["utilization_total"] = float(i)
        store.write_snapshot("s", snap2, {})
    hist = store.history("s", ["cpu_total"], 999_999, 1_001_000, max_points=10)
    assert 5 <= len(hist["cpu_total"]) <= 20        # 桶聚合后点数受控
    assert hist["cpu_total"][0][1] == pytest.approx(4.5, abs=4.6)  # 0..9 桶均值≈4.5


def test_unknown_key_raises(store, make_snapshot):
    store.write_snapshot("s", make_snapshot(), {})
    with pytest.raises(KeyError):
        store.history("s", ["bogus"], 0, 1)


def test_db_size(store, make_snapshot):
    store.write_snapshot("s", make_snapshot(), {})
    assert store.db_size() > 0


def test_agg_tables_have_indexes(store):
    rows = store._db.execute(
        "SELECT name, tbl_name FROM sqlite_master WHERE type = 'index'").fetchall()
    idx = {tbl: name for name, tbl in rows}
    assert idx.get("samples_agg") == "ix_agg_samples_agg"
    assert idx.get("gpu_samples_agg") == "ix_agg_gpu"
    assert idx.get("net_samples_agg") == "ix_agg_net"
    assert idx.get("disk_samples_agg") == "ix_agg_disk"
