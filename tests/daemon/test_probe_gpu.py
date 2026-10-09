import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2] / "daemon"))
import gpuviewer_daemon.probe.probe_script as probe  # noqa: E402

FIX = Path(__file__).parents[1] / "fixtures" / "proc"


def test_num():
    assert probe._num("87") == 87.0
    assert probe._num("[N/A]") is None
    assert probe._num("N/A") is None
    assert probe._num("") is None


def test_read_gpus():
    gpus = probe.read_gpus(str(FIX))
    assert len(gpus) == 2
    g0 = gpus[0]
    assert (g0["index"], g0["name"], g0["uuid"]) == (0, "NVIDIA L40", "GPU-aaaa-bbbb")
    assert g0["mem_used"] == 34000.0
    assert gpus[1]["fan_speed"] is None


def test_read_gpu_processes():
    gpus = probe.read_gpus(str(FIX))
    procs = probe.read_gpu_processes(str(FIX), gpus)
    assert len(procs) == 1
    p = procs[0]
    assert p["pid"] == 12345 and p["user"] == "user2" and p["gpu_index"] == 0
    assert p["gpu_mem_mb"] == 33999.0
    assert p["command"].startswith("python train.py")


def test_read_top(tmp_path, monkeypatch):
    base = tmp_path                                        # 真实 /proc 布局：base/<pid>/...
    (base / "uptime").write_text("123456.78 1\n")          # read_top 需要 uptime
    clk, page = 100, 4096
    monkeypatch.setattr(probe.os, "sysconf",
                        lambda k: clk if k == "SC_CLK_TCK" else page, raising=False)
    monkeypatch.setattr(probe, "_read_first", lambda ps: (FIX / "passwd").read_text()
                        if ps and ps[0].endswith("passwd") else probe._read(ps[0]))

    def mk(pid, uid, utime, stime, starttime, rss_pages, cmdline):
        d = base / str(pid)
        d.mkdir()
        # pid (comm) state ppid pgrp session tty tpgid flags minflt cminflt majflt
        # cmajflt utime stime cutime cstime prio nice threads itreal starttime vsize rss ...
        tail = " ".join(["S", "1", "1", "1", "0", "-1", "0", "0", "0", "0", "0",
                         str(utime), str(stime), "0", "0", "20", "0", "1", "0",
                         str(starttime), "1048576", str(rss_pages)])
        (d / "stat").write_text("%d (proc%s) %s\n" % (pid, pid, tail))
        (d / "status").write_text("Name:\tproc\nUid:\t%s\t%s\t%s\t%s\n" % (uid, uid, uid, uid))
        (d / "cmdline").write_text(cmdline)

    # uptime fixture=123456.78；elapsed = uptime - starttime/clk
    # p1: (100+100)/100=2s cpu / 2000s elapsed = 0.1%  rss=102400 pages=400MB
    mk(101, "1000", 100, 100, int((123456.78 - 2000) * clk), 102400, "")
    # p2: 2s / 200s = 1.0%  rss=204800 pages=800MB
    mk(102, "0", 100, 100, int((123456.78 - 200) * clk), 204800, "python\x00a.py\x00")
    top_cpu, top_mem = probe.read_top(str(base), n=10)
    assert top_cpu[0]["pid"] == 102 and top_cpu[0]["cpu"] == 1.0
    assert top_mem[0]["pid"] == 102 and top_mem[0]["mem"] == 800.0
    assert top_mem[0]["user"] == "root"
    assert top_cpu[0]["command"] == "python a.py"
    assert top_mem[1]["command"] == "[proc101]"          # cmdline 为空回退 comm


def test_read_top_real_layout(tmp_path):
    # 回归（C1）：生产 collect(base="/proc") 时 pid 目录与 uptime 同层，
    # read_top 必须遍历 base 本身而不是 base/proc，否则 TOP 恒为空列表。
    base = tmp_path
    (base / "uptime").write_text("123456.78 1\n")
    d = base / "42"
    d.mkdir()
    tail = " ".join(["S", "1", "1", "1", "0", "-1", "0", "0", "0", "0", "0",
                     "100", "100", "0", "0", "20", "0", "1", "0",
                     str(int((123456.78 - 100) * 100)), "1048576", "204800"])
    (d / "stat").write_text("42 (worker42) %s\n" % tail)
    (d / "status").write_text("Name:\tworker42\nUid:\t0\t0\t0\t0\n")
    (d / "cmdline").write_text("python\x00job\x00")
    top_cpu, top_mem = probe.read_top(str(base), n=10)
    assert top_cpu and top_mem                          # 修复前恒为 [] → 失败
    assert top_cpu[0]["pid"] == 42 and top_mem[0]["pid"] == 42
    assert top_cpu[0]["command"] == "python job"


def test_collect_golden(monkeypatch):
    # 用 fixtures 组装完整快照：CPU 双读 monkeypatch 同 Task2；FIX 无 pid 目录 → top 为空
    state = {"n": 0}

    def fake_sleep(_):
        state["n"] += 1
    monkeypatch.setattr(probe.time, "sleep", fake_sleep)
    real_read = probe._read

    def read_stat_twice(p):
        if p.endswith("stat") and not p.endswith("/net/dev/stat"):
            name = "stat2" if state["n"] else "stat"
            return real_read(str(FIX / name))
        return real_read(p)
    monkeypatch.setattr(probe, "_read", read_stat_twice)
    snap = probe.collect(str(FIX), interval=0, top_n=5)
    assert snap["cpu"]["cores"] == 2
    assert len(snap["gpus"]) == 2
    assert snap["memory"]["total"] == 32612364 * 1024
    assert snap["net"][0]["name"] == "eth0"
    assert isinstance(snap["ts"], float)
