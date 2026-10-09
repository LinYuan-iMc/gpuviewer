"""远端 config.toml 生成——自包含镜像版，不 import gpuviewer_daemon。

客户端快捷方式直启 pythonw 时没有 daemon/shared 的 PYTHONPATH，向导模块链
（main_window → wizard → tasks → 本模块）必须在任何启动方式下可导入。
这里镜像 daemon/gpuviewer_daemon/config.py 的 dump_config 输出格式；
tests/client/test_remote_config.py 用真实 daemon 版本逐字节校验防双源漂移。
"""
from dataclasses import dataclass, field


@dataclass
class ServerEntry:
    id: str
    name: str
    transport: str = "local"                     # local | ssh
    enabled: bool = True
    host: str | None = None
    port: int = 22
    user: str | None = None
    auth: str = "password"                       # password | key
    password: str | None = None
    key_path: str | None = None


@dataclass
class DaemonConfig:
    listen_host: str = "0.0.0.0"
    listen_port: int = 7421
    token: str = ""
    db_path: str = "data/gpuviewer.db"
    interval_s: float = 5.0
    probe_timeout_s: float = 10.0
    accept_host_keys: bool = True
    top_n: int = 10


@dataclass
class AppConfig:
    daemon: DaemonConfig = field(default_factory=DaemonConfig)
    servers: list[ServerEntry] = field(default_factory=list)


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def dump_config(cfg: AppConfig) -> str:
    d = cfg.daemon
    lines = [
        "[daemon]",
        f'listen_host = "{_esc(d.listen_host)}"',
        f"listen_port = {d.listen_port}",
        f'token = "{_esc(d.token)}"',
        f'db_path = "{_esc(d.db_path)}"',
        f"interval_s = {d.interval_s}",
        f"probe_timeout_s = {d.probe_timeout_s}",
        f"accept_host_keys = {str(d.accept_host_keys).lower()}",
        f"top_n = {d.top_n}",
        "",
    ]
    for s in cfg.servers:
        lines += ["[[servers]]", f'id = "{_esc(s.id)}"', f'name = "{_esc(s.name)}"',
                  f'transport = "{s.transport}"',
                  f"enabled = {str(s.enabled).lower()}"]
        if s.transport == "ssh":
            lines += [f'host = "{_esc(s.host)}"', f"port = {s.port}",
                      f'user = "{_esc(s.user)}"', f'auth = "{s.auth}"']
            if s.auth == "key" and s.key_path:
                lines.append(f'key_path = "{_esc(s.key_path)}"')
            elif s.password:
                lines.append(f'password = "{_esc(s.password)}"')
        lines.append("")
    return "\n".join(lines)
