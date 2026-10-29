import gpuviewer_client
import gpuviewer_daemon
import gpuviewer_shared


def test_packages_importable():
    # 三包同版（与 pyproject 的钉死由 test_version_sync 负责）
    versions = {gpuviewer_client.__version__,
                gpuviewer_daemon.__version__,
                gpuviewer_shared.__version__}
    assert len(versions) == 1
    assert versions != {""}
