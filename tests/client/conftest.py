"""客户端测试共享夹具：QSettings 隔离。

历史教训（v1.0.0 交付当日实际发生）：测试若写真实注册表，qs.clear() 会抹掉
用户已保存的 Token，导致线上客户端 401。所有需要 AppSettings 的测试一律经
make_settings 注入临时 INI；PySide6 的 setDefaultFormat 对 org/app 构造函数
无效（已实测），故不能用全局重定向，必须显式注入。
"""
import pytest
from PySide6.QtCore import QSettings


@pytest.fixture
def make_settings(tmp_path):
    def _make(**over):
        from gpuviewer_client.settings import AppSettings
        s = AppSettings(qs=QSettings(str(tmp_path / "settings.ini"),
                                     QSettings.Format.IniFormat))
        for k, v in over.items():
            setattr(s, k, v)
        return s
    return _make
