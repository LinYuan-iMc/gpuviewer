"""实机黄金校验：对 tests/fixtures/real/*/proc 的真实采集样本跑完整 collect()。

未采集 fixtures 时自动 skip（采集入口见 scripts/capture_fixtures.py，优先）。
fixtures 是入库的静态快照，GPU 数与占卡进程数直接钉死（重采后同步更新
EXPECTED 即可）；新host 未在 EXPECTED 登记时 fail，杜绝空转通过。
注意：Windows 无 os.statvfs，用确定性假值让 read_disks 走通挂载点解析；
read_top 在实机 fixtures 上同样会跑（passwd/os-release/uptime 存在），
但快照目录里没有 pid 子目录，top 进程为空是预期，不做具体进程数断言。
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[2] / "daemon"))
import gpuviewer_daemon.probe.probe_script as probe  # noqa: E402

REAL = Path(__file__).parents[1] / "fixtures" / "real"

# host（点换下划线）→ 采集时钉死的期望值（与 nvidia-smi-compute-apps 行数一致）
EXPECTED = {
    "l40": {"gpus": 8, "gpu_processes": 8},
    "rtx4090": {"gpus": 8, "gpu_processes": 4},
}


@pytest.mark.parametrize("host_dir", sorted(REAL.glob("*/proc")))
def test_real_machine_golden(host_dir, monkeypatch):
    host = host_dir.parent.name
    expected = EXPECTED.get(host)
    if expected is None:
        pytest.fail("新实机 fixtures 需在 EXPECTED 登记 gpus/gpu_processes 期望值: %s" % host)
    if not hasattr(os, "statvfs"):
        def _fake_statvfs(_mount):
            return type("S", (), {"f_frsize": 4096, "f_blocks": 1_000_000,
                                  "f_bfree": 300_000, "f_bavail": 250_000})()
        monkeypatch.setattr(os, "statvfs", _fake_statvfs, raising=False)
    snap = probe.collect(str(host_dir), interval=0.05, top_n=5)
    assert snap["errors"] == []
    assert snap["cpu"]["cores"] >= 1
    assert snap["memory"]["total"] > 1 << 30
    assert snap["disks"], "至少一个真实挂载点"
    assert all(d["pct"] <= 100.0 for d in snap["disks"])
    assert snap["net"], "至少一块物理网卡"
    assert len(snap["gpus"]) == expected["gpus"]
    for g in snap["gpus"]:
        assert 0 <= g["utilization"] <= 100
        assert g["mem_total"] is not None
        assert g["mem_used"] is not None
        assert g["mem_used"] <= g["mem_total"]
    assert len(snap["gpu_processes"]) == expected["gpu_processes"]


def test_skip_when_no_real_fixtures():
    if not REAL.exists() or not list(REAL.glob("*/proc")):
        pytest.skip("未采集实机 fixtures（优先运行 scripts/capture_fixtures.py）")
