import gpuviewer_client
import gpuviewer_daemon
import gpuviewer_shared


def test_packages_importable():
    assert gpuviewer_client.__version__ == "2.0.0"
    assert gpuviewer_daemon.__version__ == "2.0.0"
    assert gpuviewer_shared.__version__ == "2.0.0"
