import numpy as np
from gpuviewer_client.models import AlertEngine, LRUCache, ProcessTableModel, RingBuffer


def test_ring_buffer_wraps():
    rb = RingBuffer(3)
    for i in range(5):
        rb.append(float(i), float(i * 10))
    ts, v = rb.arrays()
    assert list(ts) == [2.0, 3.0, 4.0]
    assert list(v) == [20.0, 30.0, 40.0]


def test_ring_buffer_preallocated():
    rb = RingBuffer(4)
    rb.append(1.0, 1.0)
    ts, v = rb.arrays()
    assert isinstance(ts, np.ndarray) and len(ts) == 1


def test_lru_evicts():
    c = LRUCache(2)
    c.put("a", 1)
    c.put("b", 2)
    assert c.get("a") == 1          # a 变新
    c.put("c", 3)                   # 淘汰 b
    assert c.get("b") is None
    assert c.get("c") == 3


def test_process_model_diff():
    from PySide6.QtCore import QAbstractTableModel
    m = ProcessTableModel(["PID", "CPU%"], [(1, 5.0), (2, 6.0)])
    assert m.rowCount() == 2
    m.set_rows([(1, 5.0), (2, 7.0)])          # 行内变化，行数不变
    assert m.rowCount() == 2
    assert m.data(m.index(1, 1)) == "7.0"
    m.set_rows([(9, 1.0)])
    assert m.rowCount() == 1
    assert m.data(m.index(0, 0)) == "9"
    assert isinstance(m, QAbstractTableModel)


def make_state(sid="l40", status="online", disks=None, gpus=None):
    return {"id": sid, "name": sid, "status": status, "last_error": None,
            "last_success_ts": 1.0,
            "snapshot": {"disks": disks or [{"mount": "/", "pct": 50.0}],
                         "gpus": gpus or [{"index": 0, "temperature": 50.0}]}}


def test_alert_engine_transitions():
    eng = AlertEngine()
    hot = {"index": 0, "temperature": 90.0}
    full_disk = {"mount": "/", "pct": 95.0}
    ev1 = eng.evaluate([make_state()], 90.0, 85.0)          # 全部正常→无事件
    assert ev1 == []
    ev2 = eng.evaluate([make_state(status="offline")], 90.0, 85.0)
    assert any(e["kind"] == "offline" for e in ev2)
    ev3 = eng.evaluate([make_state(disks=[full_disk], gpus=[hot])], 90.0, 85.0)
    assert any(e["kind"] == "online" for e in ev3)          # 恢复 + 两条阈值告警
    kinds = [e["kind"] for e in ev3]
    assert kinds.count("disk_warn") == 1 and kinds.count("gpu_temp_warn") == 1
    ev4 = eng.evaluate([make_state(disks=[full_disk], gpus=[hot])], 90.0, 85.0)
    assert ev4 == []                                        # 持续超限不再重复报告


def test_alert_event_fields():
    """事件 dict 字段名固定：kind/level/message/server/ts（T19 托盘消费）。"""
    eng = AlertEngine()
    ev = eng.evaluate([make_state(status="offline", sid="s1")], 90.0, 85.0)
    assert ev, "offline 应产生事件"
    e = ev[0]
    assert e["kind"] == "offline"
    assert e["level"] == "error"
    assert "s1" in e["message"]
    assert e["server"] == "s1"
    assert isinstance(e["ts"], float)
