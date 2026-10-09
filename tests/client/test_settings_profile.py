"""设置：默认值脱敏、is_configured、部署档案读写。"""
from gpuviewer_client.settings import AppSettings
from PySide6.QtCore import QSettings


def _ini(tmp_path):
    return QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)


def test_default_base_url_sanitized(make_settings):
    s = make_settings()
    assert s.base_url == "http://127.0.0.1:7421"
    assert not s.is_configured
    s.token = "abc"
    assert s.is_configured


def test_deploy_profile_roundtrip(make_settings, tmp_path):
    s = make_settings()
    s.deploy_profile = {"master_id": "l40", "host": "h", "password": "p"}
    s2 = AppSettings(qs=_ini(tmp_path))
    assert s2.deploy_profile == {"master_id": "l40", "host": "h", "password": "p"}
    s2.deploy_profile = None
    assert AppSettings(qs=_ini(tmp_path)).deploy_profile is None


def test_deploy_profile_corrupt_falls_back_to_none(make_settings, tmp_path):
    make_settings().qs.setValue("deploy_profile", "!!!not-base64!!!")
    assert AppSettings(qs=_ini(tmp_path)).deploy_profile is None
