"""守护进程 TOML 配置。读取用 tomllib(3.11+)/tomli，写回用针对本 schema 的极简序列化。"""
import sys
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

if sys.version_info >= (3, 11):
    import tomllib
else:                                              # pragma: no cover
    import tomli as tomllib


class ServerEntry(BaseModel):
    id: str
    name: str
    transport: str = "local"                      # local | ssh
    enabled: bool = True
    host: str | None = Field(default=None, validate_default=True)
    port: int = 22
    user: str | None = Field(default=None, validate_default=True)
    auth: str = "password"                        # password | key
    password: str | None = None
    key_path: str | None = None

    @field_validator("transport")
    @classmethod
    def _check_transport(cls, v):
        if v not in ("local", "ssh"):
            raise ValueError("transport must be local or ssh")
        return v

    @field_validator("host", "user")
    @classmethod
    def _check_ssh_fields(cls, v, info):
        entry = info.data
        if entry.get("transport") == "ssh" and not v and info.field_name in ("host", "user"):
            raise ValueError(f"ssh server requires {info.field_name}")
        return v


class DaemonConfig(BaseModel):
    listen_host: str = "0.0.0.0"
    listen_port: int = 7421
    token: str = ""
    db_path: str = "data/gpuviewer.db"
    interval_s: float = 5.0
    probe_timeout_s: float = 10.0
    accept_host_keys: bool = True
    top_n: int = 10


class AppConfig(BaseModel):
    daemon: DaemonConfig = DaemonConfig()
    servers: list[ServerEntry] = []


def load_config(path) -> AppConfig:
    with open(path, "rb") as f:
        data = tomllib.load(f)
    return AppConfig(**data)


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def dump_config(cfg: AppConfig) -> str:
    """序列化为 TOML 文本（客户端部署向导也要用它生成远端 config.toml）。"""
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


def save_config(path, cfg: AppConfig) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(dump_config(cfg), encoding="utf-8")
