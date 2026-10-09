import asyncio
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parents[2] / "daemon"))
from gpuviewer_daemon.probe import runner  # noqa: E402


def test_probe_b64_is_valid():
    import base64
    src = base64.b64decode(runner.PROBE_B64).decode()
    assert "def collect(" in src
    assert "nvidia-smi" in src


@pytest.mark.asyncio
async def test_local_runner_returns_snapshot(monkeypatch):
    fake = {"ts": 1.0, "gpus": [], "errors": []}

    async def fake_exec(self, payload, timeout):
        return json.dumps(fake)

    monkeypatch.setattr(runner.LocalRunner, "_exec", fake_exec)
    out = await runner.LocalRunner().run()
    assert out == fake


@pytest.mark.asyncio
async def test_local_runner_real_end_to_end():
    # 真实在本机执行探针（Windows 下无 /proc，sections 容错进 errors）
    out = await runner.LocalRunner().run()
    assert "ts" in out and "errors" in out
    if sys.platform != "win32":                       # Linux 有 /proc 才断言核数
        assert out["cpu"]["cores"] >= 1


def _fake_asyncssh(monkeypatch, captured):
    fake = ModuleType("asyncssh")

    async def fake_connect(**kwargs):
        captured.append(kwargs)
        raise OSError("simulated unreachable")        # 模拟连不上，仅捕获 kwargs

    fake.connect = fake_connect
    monkeypatch.setitem(sys.modules, "asyncssh", fake)


def _ssh_entry():
    return SimpleNamespace(transport="ssh", host="h1", port=22, user="u", auth="password",
                           password="pw", key_path=None)


@pytest.mark.asyncio
async def test_ssh_runner_host_key_semantics(monkeypatch):
    captured = []
    _fake_asyncssh(monkeypatch, captured)

    with pytest.raises(runner.ProbeError):
        await runner.SshRunner(_ssh_entry(), accept_host_keys=False).run(timeout=1)
    assert "known_hosts" not in captured[-1]           # False → 走默认严格校验
    assert captured[-1]["host"] == "h1" and captured[-1]["password"] == "pw"

    with pytest.raises(runner.ProbeError):
        await runner.SshRunner(_ssh_entry(), accept_host_keys=True).run(timeout=1)
    assert captured[-1]["known_hosts"] is None         # True → 无条件接受（已知取舍）


@pytest.mark.asyncio
async def test_make_runner_passthrough():
    ssh_entry = SimpleNamespace(transport="ssh")
    r = runner.make_runner(ssh_entry, accept_host_keys=False)
    assert isinstance(r, runner.SshRunner) and r._accept is False
    assert runner.make_runner(ssh_entry)._accept is True
    assert isinstance(runner.make_runner(SimpleNamespace(transport="local")),
                      runner.LocalRunner)


# ---- 修复轮 R2：top_n 配置接线至探针载荷 ----

def test_make_runner_passthrough_top_n():
    """I-2：make_runner 透传 top_n（默认 10），两种 runner 均持有。"""
    r = runner.make_runner(SimpleNamespace(transport="local"), top_n=3)
    assert isinstance(r, runner.LocalRunner) and r._top_n == 3
    r2 = runner.make_runner(_ssh_entry(), accept_host_keys=True, top_n=7)
    assert isinstance(r2, runner.SshRunner) and r2._top_n == 7
    assert runner.make_runner(SimpleNamespace(transport="local"))._top_n == 10
    assert runner.LocalRunner()._top_n == 10


def test_remote_cmd_appends_top_n():
    """I-2：远程命令在管道后追加执行参数（python3 - <N>）。"""
    cmd = runner._remote_cmd(5)
    assert cmd.startswith("echo ") and cmd.endswith("| python3 - 5")
    assert runner.PROBE_B64 in cmd


@pytest.mark.asyncio
async def test_local_runner_argv_carries_top_n(monkeypatch):
    """I-2：LocalRunner 以 `python -c <code> <N>` 启动——-c 代码后的 argv
    成为被 exec 探针的 sys.argv[1]。"""
    seen = {}

    class FakeProc:
        returncode = 0

        async def communicate(self):
            return b'{"ts": 1.0}', b""

        def kill(self):
            pass

        async def wait(self):
            return 0

    async def fake_create(*argv, **kw):
        seen["argv"] = argv
        return FakeProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create)
    out = await runner.LocalRunner(top_n=3).run(timeout=2)
    assert out == {"ts": 1.0}
    assert seen["argv"][1] == "-c" and seen["argv"][-1] == "3"


def test_probe_script_main_accepts_top_n():
    """I-2：探针 main() 读 sys.argv[1] 为 top_n——subprocess 直调脚本验证
    （Windows 无 /proc 时 top 表为空，断言不崩且键存在、长度不超限）。"""
    import subprocess
    script = Path(runner.__file__).parent / "probe_script.py"
    out = subprocess.run([sys.executable, str(script), "3"],
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    assert out.returncode == 0, out.stderr.decode("utf-8", "replace")
    snap = json.loads(out.stdout.decode("utf-8"))
    assert "ts" in snap and "top_cpu" in snap and "top_mem" in snap
    assert len(snap["top_cpu"]) <= 3 and len(snap["top_mem"]) <= 3


@pytest.mark.asyncio
async def test_local_runner_real_end_to_end_top_n():
    """I-2：真实在本机以 top_n=3 执行探针载荷（Linux 上断言表长 ≤3，
    Windows 无 /proc 时退化为断言键存在——见 test_probe_script_main_accepts_top_n）。"""
    out = await runner.LocalRunner(top_n=3).run()
    assert "ts" in out and "top_cpu" in out and "top_mem" in out
    if sys.platform != "win32":
        assert len(out["top_cpu"]) <= 3 and len(out["top_mem"]) <= 3
