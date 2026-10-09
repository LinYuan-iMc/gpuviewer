from gpuviewer_shared.schemas import Snapshot


def test_snapshot_accepts_minimal():
    snap = Snapshot(ts=1.0)
    assert snap.host.hostname == ""
    assert snap.gpus == []
    assert snap.cpu.cores == 0


def test_snapshot_accepts_full(make_snapshot):
    snap = Snapshot(**make_snapshot())
    assert snap.cpu.utilization_total == 12.5
    assert snap.gpus[0].mem_total == 46068
    assert snap.gpu_processes[0].gpu_index == 0
