"""DeployWorkflow：FakeTransport 脚本化驱动，验证配置生成、复用与兜底分支。"""
import re

import pytest
from gpuviewer_client.deploy.tasks import (
    DeployError,
    DeployWorkflow,
    ServerSpec,
    generate_token,
    make_id,
)

try:
    import tomllib
except ModuleNotFoundError:                    # pragma: no cover
    import tomli as tomllib

EXISTING = b"""[daemon]
listen_host = "0.0.0.0"
listen_port = 7421
token = "oldtoken123"
db_path = "data/gpuviewer.db"

[[servers]]
id = "l40"
name = "L40"
transport = "local"
enabled = true
"""


class FakeTransport:
    def __init__(self, existing=None, install_exit=0, python="3.10.12", gpu=True):
        self.existing = existing
        self.install_exit = install_exit
        self.python = python
        self.gpu = gpu
        self.runs = []
        self.writes = {}

    async def run(self, cmd, timeout=60):
        self.runs.append(cmd)
        if "sys.version" in cmd:
            return 0, self.python + "\n", ""
        if "nvidia-smi" in cmd:
            return 0, ("yes\n" if self.gpu else "no\n"), ""
        if "$HOME" in cmd:
            return 0, "/home/u", ""
        if "deploy_remote.sh" in cmd:
            return self.install_exit, "install output", ""
        if "start_nohup.sh" in cmd:
            return 0, "started pid 1", ""
        return 0, "", ""

    async def exists(self, path):
        return path.endswith("config.toml") and self.existing is not None

    async def read_file(self, path):
        return self.existing if path.endswith("config.toml") else None

    async def write_file(self, path, data, mode=0o644):
        self.writes[path] = (data, mode)


def health_ok(base_url, token):
    return {"version": "test", "uptime_s": 1}


def health_fail(base_url, token):
    raise RuntimeError("conn refused")


def specs():
    master = ServerSpec(name="L40 机", host="10.0.1.1", user="u1", password="p1")
    other = ServerSpec(name="4090", host="10.0.1.2", user="u2", password="p2")
    return master, other


async def test_fresh_deploy_generates_config():
    t = FakeTransport()
    m, o = specs()
    r = await DeployWorkflow(m, [o], t, health_get=health_ok).run()
    assert not r.reused and not r.nohup_fallback
    assert r.base_url == "http://10.0.1.1:7421"
    assert any("deploy_remote.sh" in c for c in t.runs)
    data, mode = t.writes["/home/u/gpuviewer/config.toml"]
    assert mode == 0o600
    cfg = tomllib.loads(data.decode())
    assert cfg["daemon"]["token"] == r.token
    assert cfg["daemon"]["interval_s"] == 1.0
    assert cfg["servers"][0] == {"id": "l40", "name": "L40 机",
                                 "transport": "local", "enabled": True}
    assert cfg["servers"][1]["transport"] == "ssh"
    assert cfg["servers"][1]["host"] == "10.0.1.2"
    assert cfg["servers"][1]["password"] == "p2"


async def test_reuse_deploy_preserves_token():
    t = FakeTransport(existing=EXISTING)
    m, _ = specs()
    r = await DeployWorkflow(m, [], t, health_get=health_ok).run()
    assert r.reused and r.token == "oldtoken123" and r.master_id == "l40"
    assert not any(p.endswith("config.toml") for p in t.writes)


async def test_systemd_failure_falls_back_to_nohup():
    t = FakeTransport(install_exit=3)
    m, _ = specs()
    r = await DeployWorkflow(m, [], t, health_get=health_ok).run()
    assert r.nohup_fallback
    assert any("start_nohup.sh" in c for c in t.runs)
    assert any("linger" in n for n in r.notes)


async def test_install_failure_raises_with_output():
    t = FakeTransport(install_exit=1)
    m, _ = specs()
    with pytest.raises(DeployError, match="exit 1"):
        await DeployWorkflow(m, [], t, health_get=health_ok).run()


async def test_old_python_rejected():
    t = FakeTransport(python="3.8.9")
    m, _ = specs()
    with pytest.raises(DeployError, match="3.9"):
        await DeployWorkflow(m, [], t, health_get=health_ok).run()


async def test_no_gpu_only_warns():
    t = FakeTransport(gpu=False)
    m, _ = specs()
    r = await DeployWorkflow(m, [], t, health_get=health_ok).run()
    assert any("nvidia-smi" in n for n in r.notes)


async def test_health_failure_mentions_firewall():
    t = FakeTransport()
    m, _ = specs()
    wf = DeployWorkflow(m, [], t, health_get=health_fail, health_tries=2)
    with pytest.raises(DeployError, match="7421"):
        await wf.run()


async def test_cancel_between_steps():
    t = FakeTransport()
    m, _ = specs()
    wf = DeployWorkflow(m, [], t, health_get=health_ok)
    wf.cancel()
    with pytest.raises(DeployError, match="取消"):
        await wf.run()


def test_make_id_sanitizes_and_dedupes():
    taken = set()
    assert make_id("L40 机", "h", taken) == "l40"
    assert make_id("L40", "h", taken) == "l40-2"
    assert make_id("  ", "Host9", taken) == "host9"


def test_generate_token_alnum():
    for _ in range(20):
        assert re.fullmatch(r"[A-Za-z0-9]{20,}", generate_token())
