"""版本单一源校验：三个包的 __version__ 必须与 pyproject [project].version 一致。"""
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:                    # pragma: no cover
    import tomli as tomllib

REPO = Path(__file__).resolve().parents[1]


def test_versions_synced_with_pyproject():
    data = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    declared = data["project"]["version"]
    import gpuviewer_client
    import gpuviewer_daemon
    import gpuviewer_shared
    assert gpuviewer_client.__version__ == declared
    assert gpuviewer_daemon.__version__ == declared
    assert gpuviewer_shared.__version__ == declared
