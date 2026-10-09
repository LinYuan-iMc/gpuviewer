import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2] / "daemon"))
import gpuviewer_daemon.probe.probe_script as probe  # noqa: E402

FIX = Path(__file__).parents[1] / "fixtures" / "proc"


def test_cpu_delta_pure():
    a = probe._parse_stat((FIX / "stat").read_text())
    b = probe._parse_stat((FIX / "stat2").read_text())
    total = probe._pct(a[0], b[0])
    per_core = [probe._pct(x, y) for x, y in zip(a[1], b[1])]
    assert per_core[0] == 100.0      # idle 不变 → 满载
    assert per_core[1] == 0.0        # idle 增长 = 总增量 → 空闲
    assert 0.0 < total < 100.0


def test_read_cpu(monkeypatch):
    state = {"n": 0}

    def fake_sleep(_):
        state["n"] += 1
    orig = probe._read
    monkeypatch.setattr(probe.time, "sleep", fake_sleep)
    monkeypatch.setattr(probe, "_read", lambda p: orig(
        str(FIX / ("stat2" if state["n"] else "stat"))) if p.endswith("stat")
        else (FIX / "loadavg").read_text())
    cpu = probe.read_cpu(str(FIX), interval=0)
    assert cpu["cores"] == 2
    assert cpu["load1"] == 0.52
    assert cpu["utilization_per_core"][0] == 100.0


def test_read_mem():
    mem = probe.read_mem(str(FIX))
    assert mem["total"] == 32612364 * 1024
    assert mem["used"] == (32612364 - 20123456) * 1024
    assert mem["swap_used"] == (8388604 - 8388512) * 1024


def test_disks_from_lines():
    calls = {}

    def fake_statvfs(mount):
        calls[mount] = True
        # f_bsize f_frsize f_blocks f_bfree f_bavail ...
        return type("S", (), {"f_frsize": 1024, "f_blocks": 1_000_000,
                              "f_bfree": 300_000, "f_bavail": 250_000})()
    devs = {"/": 1, "/data": 2, "/boot": 3}

    def fake_stat(p):
        return type("D", (), {"st_dev": devs.get(p, 99)})()
    disks = probe._disks_from_lines((FIX / "mounts").read_text().splitlines(),
                                    fake_statvfs, fake_stat)
    mounts = [d["mount"] for d in disks]
    assert mounts == ["/", "/data", "/boot"]          # 伪文件系统被过滤
    assert calls == {"/": True, "/data": True, "/boot": True}
    assert disks[0]["total"] == 1_000_000 * 1024
    assert disks[0]["used"] == 700_000 * 1024         # f_blocks - f_bfree
    assert disks[0]["avail"] == 250_000 * 1024        # df 语义用 f_bavail
    assert disks[0]["pct"] == 73.7                    # used/(used+avail)


def test_disks_dedup_same_fs():
    """同一文件系统挂多个路径（bind mount）→ 按 st_dev 去重，保留首个挂载点。"""
    lines = [
        "/dev/sda2 / ext4 rw 0 0",
        "/dev/sda2 /home/CNU ext4 rw 0 0",
        "/dev/sdb1 /mnt/other ext4 rw 0 0",
        "tmpfs /run tmpfs rw 0 0",
    ]

    def fake_statvfs(_):
        return type("S", (), {"f_frsize": 1024, "f_blocks": 1_000_000,
                              "f_bfree": 300_000, "f_bavail": 250_000})()
    devs = {"/": 7, "/home/CNU": 7, "/mnt/other": 9}

    def fake_stat(p):
        return type("D", (), {"st_dev": devs[p]})()
    disks = probe._disks_from_lines(lines, fake_statvfs, fake_stat)
    assert [d["mount"] for d in disks] == ["/", "/mnt/other"]


def test_disks_stat_fail_no_dedup():
    """st_dev 不可得（权限/不存在）时不丢行——宁可重复不可漏报。"""
    lines = [
        "/dev/sda2 / ext4 rw 0 0",
        "/dev/sda2 /data ext4 rw 0 0",
    ]

    def fake_statvfs(_):
        return type("S", (), {"f_frsize": 1024, "f_blocks": 1_000_000,
                              "f_bfree": 300_000, "f_bavail": 250_000})()

    def fake_stat(_):
        raise OSError("cannot stat")
    disks = probe._disks_from_lines(lines, fake_statvfs, fake_stat)
    assert [d["mount"] for d in disks] == ["/", "/data"]


def test_read_net():
    net = probe.read_net(str(FIX))
    assert [i["name"] for i in net] == ["eth0"]
    assert net[0]["rx_bytes"] == 987654321


def test_read_host(monkeypatch):
    orig = probe._read
    monkeypatch.setattr(probe, "_read", lambda p: orig(str(FIX / "uptime"))
                        if p.endswith("uptime") else (FIX / "os-release").read_text())
    host = probe.read_host(str(FIX))
    assert host["uptime_s"] == 123456.78
    assert host["os_release"] == "Ubuntu 22.04.4 LTS"


def test_read_gpus_accepts_prefetched_text():
    """并行预取路径：read_gpus/read_gpu_processes 直接解析传入文本。"""
    text = ("0, NVIDIA L40, GPU-abc, 12, 34, 1000, 2000, 41, 120.5, 300, 30\n"
            "1, NVIDIA L40, GPU-def, 87, 98, 44000, 46000, 66, 250.1, 300, 60\n")
    gpus = probe.read_gpus("/nonexistent", text)
    assert len(gpus) == 2
    assert gpus[0]["name"] == "NVIDIA L40" and gpus[0]["index"] == 0
    assert gpus[1]["mem_used"] == 44000

    apps = ("GPU-abc, 111, python, 500\n"
            "GPU-def, 222, python, 40000\n")
    procs = probe.read_gpu_processes("/nonexistent", gpus, apps)
    assert len(procs) == 2
    assert procs[1]["gpu_index"] == 1        # uuid→index 映射生效


def test_nvidia_launch_fixture_mode(tmp_path):
    """fixture 目录（nvidia-smi-gpu.txt 存在）→ 不点火 Popen。"""
    (tmp_path / "nvidia-smi-gpu.txt").write_text(
        "0, T, GPU-x, 1, 2, 3, 4, 5, 6, 7, 8\n", encoding="utf-8")
    pg, pp, pm = probe._nvidia_launch(str(tmp_path))
    assert pg is None and pp is None and pm is None
    assert probe._nvidia_collect(pg) is None


def test_gpu_processes_new_ps_fields(tmp_path):
    """ps 新格式（含 pcpu/pmem/rss）→ cpu_pct/host_mem 字段进快照。"""
    tmp_path.joinpath("nvidia-smi-compute-apps.txt").write_text(
        "GPU-abc, 111, python, 4096\n", encoding="utf-8")
    tmp_path.joinpath("ps-gpu.txt").write_text(
        "111 user2 3-05:41:27 99.2 4.1 5242880 python train.py --lr 3e-4\n",
        encoding="utf-8")
    procs = probe.read_gpu_processes(str(tmp_path), [
        {"uuid": "GPU-abc", "index": 2}])
    assert len(procs) == 1
    p = procs[0]
    assert p["cpu_pct"] == 99.2 and p["host_mem_pct"] == 4.1
    assert p["host_mem_kb"] == 5242880
    assert p["command"] == "python train.py --lr 3e-4"


def test_gpu_processes_old_fixture_format(tmp_path):
    """旧 4 字段 fixture（无新指标）→ 旧字段照常、新字段为 None。"""
    tmp_path.joinpath("nvidia-smi-compute-apps.txt").write_text(
        "GPU-x, 222, python, 1024\n", encoding="utf-8")
    tmp_path.joinpath("ps-gpu.txt").write_text(
        "222 user2 1:00:00 VLLM::EngineCore\n", encoding="utf-8")
    procs = probe.read_gpu_processes(str(tmp_path), [{"uuid": "GPU-x", "index": 0}])
    assert procs[0]["user"] == "user2" and procs[0]["elapsed"] == "1:00:00"
    assert procs[0]["cpu_pct"] is None and procs[0]["host_mem_kb"] is None


def test_parse_pmon():
    """pmon 输出 → pid → (sm%, 带宽%)；表头/空行跳过。"""
    text = ("# gpu        pid  type    sm   mem   enc   dec   command\n"
            "# Idx          #   C/G     %     %     %     %   name\n"
            "    0       111     C     87     4     0     0   python\n"
            "    1       222     C      0     0     0     0   Xorg\n"
            "\n")
    from gpuviewer_daemon.probe.probe_script import _parse_pmon
    d = _parse_pmon(text)
    assert d["111"] == (87.0, 4.0) and d["222"] == (0.0, 0.0)
    assert _parse_pmon("") == {} and _parse_pmon(None) == {}


def test_gpu_processes_with_pmon(tmp_path):
    """pmon fixture 文件 → sm_pct/mem_bw_pct 进快照。"""
    tmp_path.joinpath("nvidia-smi-compute-apps.txt").write_text(
        "GPU-abc, 111, python, 4096\n", encoding="utf-8")
    tmp_path.joinpath("ps-gpu.txt").write_text(
        "111 user2 1:00:00 5.0 2.0 1048576 python train.py\n", encoding="utf-8")
    tmp_path.joinpath("nvidia-smi-pmon.txt").write_text(
        "# gpu pid type sm mem enc dec command\n"
        "    0  111     C   87   4   0   0  python\n", encoding="utf-8")
    procs = probe.read_gpu_processes(str(tmp_path), [{"uuid": "GPU-abc", "index": 1}])
    assert procs[0]["sm_pct"] == 87.0 and procs[0]["mem_bw_pct"] == 4.0
