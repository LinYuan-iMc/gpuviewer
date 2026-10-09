"""部署载荷清单：构建远端 ~/gpuviewer 布局的上传清单。

静态脚本/依赖清单是仓库源的逐字节副本（tests 强制同步，防止双源漂移）；
两个 Python 包经 importlib.resources 定位——仓库布局（启动器 PYTHONPATH 含
daemon/shared）与未来的 pip 安装均适用。所有文本在清单构建时统一 CRLF→LF：
Windows 工作区文件上传到 Linux 必须保持 LF，带 \r 的 bash 脚本在远端直接跑挂。
"""
import os
import sys
from importlib import resources
from pathlib import Path

FILES_DIR = Path(__file__).resolve().parent / "files"

# (嵌入文件名, 远端相对路径, 权限)——相对部署目录 ~/gpuviewer
STATIC_PAYLOAD = [
    ("deploy_remote.sh", "deploy_remote.sh", 0o755),
    ("gpuviewer.service", "gpuviewer.service", 0o644),
    ("start_nohup.sh", "start_nohup.sh", 0o755),
    ("daemon_requirements.txt", "daemon/requirements.txt", 0o644),
]

# 随客户端分发的 Python 包 → 远端相对目录
PACKAGE_PAYLOAD = [
    ("gpuviewer_daemon", "daemon/gpuviewer_daemon"),
    ("gpuviewer_shared", "shared/gpuviewer_shared"),
]

EXCLUDE_DIRS = {"__pycache__", ".pytest_cache"}


# 包名 → 仓库布局子目录（快捷方式直启无 PYTHONPATH 时的回退定位）
_REPO_SUBDIR = {"gpuviewer_daemon": "daemon", "gpuviewer_shared": "shared"}


def normalize(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n")


def _repo_pkg_dir(package: str) -> Path | None:
    """仓库布局回退：client/gpuviewer_client/deploy/ 向上三级是仓库根。"""
    root = Path(__file__).resolve().parents[3]
    cand = root / _REPO_SUBDIR.get(package, package) / package
    return cand if cand.is_dir() else None


def _pkg_dir(package: str) -> Path:
    # ① PyInstaller 冻结环境：daemon/shared 源码由 release.spec 作为 datas
    #    打入 _MEIPASS（冻结态下没有 site-packages 源码，必须走这里）
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass is not None:
        frozen = Path(meipass) / package
        if frozen.is_dir():
            return frozen
    try:
        p = Path(str(resources.files(package)))
        if p.is_dir():
            return p
    except Exception:                                            # noqa: BLE001
        pass
    fb = _repo_pkg_dir(package)
    if fb is not None:
        return fb
    raise RuntimeError(f"包 {package} 无法定位（既不可导入，仓库布局回退也失败）")


def _pkg_files(package: str) -> list[tuple[str, bytes]]:
    root = _pkg_dir(package)
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        for fn in filenames:
            if fn.endswith((".pyc", ".pyo")):
                continue
            rel = (Path(dirpath) / fn).relative_to(root)
            out.append((rel.as_posix(), (Path(dirpath) / fn).read_bytes()))
    out.sort()
    return out


def build_manifest() -> list[tuple[str, bytes, int]]:
    """[(远端相对路径, 内容, 权限)]，按路径排序保证确定性；文本统一 LF。"""
    items: list[tuple[str, bytes, int]] = []
    for fn, rel, mode in STATIC_PAYLOAD:
        items.append((rel, normalize((FILES_DIR / fn).read_bytes()), mode))
    for pkg, reldir in PACKAGE_PAYLOAD:
        for rel, data in _pkg_files(pkg):
            items.append((f"{reldir}/{rel}", normalize(data), 0o644))
    items.sort(key=lambda t: t[0])
    return items
