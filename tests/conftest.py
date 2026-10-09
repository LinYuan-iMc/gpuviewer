import pytest


@pytest.fixture
def make_snapshot():
    def _make(**over):
        snap = {
            "ts": 1710000000.0,
            "errors": [],
            "host": {"hostname": "l40", "os_release": "Ubuntu 22.04.4 LTS",
                     "kernel": "5.15.0", "uptime_s": 123456.78},
            "cpu": {"cores": 2, "utilization_total": 12.5,
                    "utilization_per_core": [20.0, 5.0],
                    "load1": 0.52, "load5": 0.58, "load15": 0.59},
            "memory": {"total": 33395693056, "used": 13272248320,
                       "available": 20123459584, "cached": 10353381376,
                       "swap_total": 8589930496, "swap_used": 94208},
            "disks": [{"mount": "/", "total": 1000, "used": 700, "avail": 300, "pct": 70.0}],
            "gpus": [{"index": 0, "name": "NVIDIA L40", "uuid": "GPU-aaaa",
                      "utilization": 87.0, "mem_utilization": 55.0, "mem_used": 34000,
                      "mem_total": 46068, "temperature": 45.0, "power_draw": 180.5,
                      "power_limit": 300.0, "fan_speed": 30.0}],
            "gpu_processes": [{"pid": 12345, "user": "user2", "command": "python train.py",
                               "gpu_mem_mb": 33999.0, "gpu_index": 0, "elapsed": "1-02:03:04"}],
            "net": [{"name": "eth0", "rx_bytes": 987654321, "tx_bytes": 123456789}],
            "top_cpu": [{"pid": 1, "user": "root", "cpu": 0.1, "mem": 0.5, "command": "init"}],
            "top_mem": [{"pid": 1, "user": "root", "cpu": 0.1, "mem": 0.5, "command": "init"}],
        }
        snap.update(over)
        return snap
    return _make


@pytest.fixture
def client_payload(make_snapshot):
    return {"version": "1.0.0",
            "servers": [{"id": "l40", "name": "L40", "status": "online",
                         "last_error": None, "last_success_ts": 1.0,
                         "snapshot": make_snapshot()}]}
