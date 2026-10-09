"""镜像版配置序列化与真实 daemon 版本的逐字节同步；客户端包自包含性。

第二项防的是 2026-10-08 线上事故：向导模块链 import 了 gpuviewer_daemon，
用户快捷方式（pythonw 直启、无 PYTHONPATH）下客户端启动即无声崩溃——
崩溃发生在日志初始化之前，client.log 里什么都不留。
"""
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def test_dump_config_sync_with_daemon():
    from gpuviewer_client.deploy.remote_config import AppConfig as CApp
    from gpuviewer_client.deploy.remote_config import DaemonConfig as CDae
    from gpuviewer_client.deploy.remote_config import ServerEntry as CSrv
    from gpuviewer_client.deploy.remote_config import dump_config as c_dump
    from gpuviewer_daemon.config import AppConfig as DApp
    from gpuviewer_daemon.config import DaemonConfig as DDae
    from gpuviewer_daemon.config import ServerEntry as DSrv
    from gpuviewer_daemon.config import dump_config as d_dump

    cases = [
        (CApp(), DApp()),
        (CApp(daemon=CDae(token="tok", interval_s=1.0), servers=[
            CSrv(id="a", name="A 机", transport="local"),
            CSrv(id="b", name='B "x"', transport="ssh", host="h", port=2222,
                 user="u", auth="password", password='p@ss"\\'),
         ]),
         DApp(daemon=DDae(token="tok", interval_s=1.0), servers=[
            DSrv(id="a", name="A 机", transport="local"),
            DSrv(id="b", name='B "x"', transport="ssh", host="h", port=2222,
                 user="u", auth="password", password='p@ss"\\'),
         ])),
    ]
    for ccfg, dcfg in cases:
        assert c_dump(ccfg) == d_dump(dcfg), "客户端镜像序列化与 daemon 版本漂移"


def test_client_importable_without_daemon_path():
    """快捷方式启动环境（cwd=client、无 daemon PYTHONPATH）客户端必须自包含可导入。"""
    code = ("import gpuviewer_client.ui.main_window;"
            "import gpuviewer_client.deploy.payload as p;"
            "m = p.build_manifest();"
            "assert any(r.endswith('gpuviewer_daemon/app.py') for r, _, _ in m);"
            "print('SELF_CONTAINED', len(m))")
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    r = subprocess.run([sys.executable, "-c", code], cwd=str(REPO / "client"),
                       capture_output=True, text=True, env=env, timeout=120)
    assert r.returncode == 0, r.stderr
    assert "SELF_CONTAINED" in r.stdout
