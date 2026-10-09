from pathlib import Path

import pytest
from gpuviewer_daemon.config import AppConfig, DaemonConfig, ServerEntry, load_config, save_config


def test_ssh_entry_requires_host_user():
    with pytest.raises(Exception):
        ServerEntry(id="x", name="x", transport="ssh")
    ServerEntry(id="y", name="y", transport="ssh", host="1.2.3.4", user="u")


def test_roundtrip(tmp_path: Path):
    cfg = AppConfig(daemon=DaemonConfig(token="secret", db_path=str(tmp_path / "x.db")),
                    servers=[ServerEntry(id="l40", name="L40", transport="local"),
                             ServerEntry(id="s2", name="4090", transport="ssh",
                                         host="192.168.1.11", user="user2",
                                         password="pw", auth="password")])
    p = tmp_path / "config.toml"
    save_config(p, cfg)
    assert "password = \"pw\"" in p.read_text(encoding="utf-8")
    cfg2 = load_config(p)
    assert cfg2.servers[1].host == "192.168.1.11"
    assert cfg2.daemon.token == "secret"
    assert cfg2 == cfg


def test_defaults(tmp_path: Path):
    p = tmp_path / "c.toml"
    p.write_text("[daemon]\n", encoding="utf-8")
    cfg = load_config(p)
    assert cfg.daemon.listen_port == 7421
    assert cfg.servers == []
