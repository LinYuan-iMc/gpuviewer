"""部署载荷清单：完整性、LF 归一、嵌入副本与仓库源逐字节同步。"""
from pathlib import Path

from gpuviewer_client.deploy.payload import FILES_DIR, build_manifest

REPO = Path(__file__).resolve().parents[2]

# 嵌入副本必须与仓库源同步（防双源漂移；改了源文件忘了拷贝会在这里炸）
SYNC_PAIRS = [
    ("deploy_remote.sh", "scripts/deploy_remote.sh"),
    ("gpuviewer.service", "daemon/deploy/gpuviewer.service"),
    ("start_nohup.sh", "daemon/deploy/start_nohup.sh"),
    ("daemon_requirements.txt", "daemon/requirements.txt"),
]


def test_manifest_core_files():
    m = {rel: data for rel, data, _ in build_manifest()}
    for rel in ["deploy_remote.sh", "gpuviewer.service", "start_nohup.sh",
                "daemon/requirements.txt", "daemon/gpuviewer_daemon/app.py",
                "daemon/gpuviewer_daemon/api.py", "shared/gpuviewer_shared/schemas.py"]:
        assert rel in m and m[rel], rel


def test_manifest_lf_only():
    for rel, data, _ in build_manifest():
        assert b"\r" not in data, rel


def test_manifest_excludes_cache():
    for rel, _, _ in build_manifest():
        assert "__pycache__" not in rel and not rel.endswith(".pyc")


def test_embedded_files_sync_with_repo():
    for emb, src in SYNC_PAIRS:
        assert (FILES_DIR / emb).read_bytes() == (REPO / src).read_bytes(), emb


def test_manifest_from_frozen_meipass(tmp_path, monkeypatch):
    """PyInstaller 冻结态：daemon/shared 源码在 _MEIPASS 下，清单必须可构建。"""
    import gpuviewer_client.deploy.payload as pl
    fake = tmp_path / "gpuviewer_daemon"
    fake.mkdir()
    (fake / "app.py").write_text("# frozen copy\n")
    monkeypatch.setattr(pl.sys, "_MEIPASS", str(tmp_path), raising=False)
    m = dict((rel, data) for rel, data, _ in pl.build_manifest())
    assert "daemon/gpuviewer_daemon/app.py" in m
    assert b"frozen copy" in m["daemon/gpuviewer_daemon/app.py"]
