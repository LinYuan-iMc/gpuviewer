"""客户端设置（QSettings 持久化，注册表/INI 由 Qt 决定）。

deploy_profile 存总服务端 SSH 凭据（承诺"仅首次部署需要输入密码"）：base64
仅防直接裸读、不防盗取，与 daemon 端 config.toml 明文持有密码的既有姿态一致。
"""
import base64
import json

from PySide6.QtCore import QSettings


class AppSettings:
    DEFAULTS = {"base_url": "http://127.0.0.1:7421", "token": "", "interval_s": 1.0,
                "disk_warn_pct": 90.0, "gpu_temp_warn": 85.0}

    def __init__(self, qs=None):
        # qs 可注入（测试用临时 INI，绝不触碰真实注册表——见 tests/client/conftest.py）
        self.qs = qs if qs is not None else QSettings("GPUViewer", "GPUViewer")
        for k, v in self.DEFAULTS.items():
            stored = self.qs.value(k, v)
            setattr(self, k, type(v)(stored))

    def save(self):
        for k in self.DEFAULTS:
            self.qs.setValue(k, getattr(self, k))
        self.qs.sync()

    @property
    def is_configured(self) -> bool:
        """是否已完成初始化（拿到 daemon 地址与 token）。"""
        return bool(self.token)

    @property
    def deploy_profile(self) -> dict | None:
        raw = self.qs.value("deploy_profile", "")
        if not raw:
            return None
        try:
            data = json.loads(base64.b64decode(str(raw)))
            return data if isinstance(data, dict) else None
        except Exception:                                        # noqa: BLE001
            return None

    @deploy_profile.setter
    def deploy_profile(self, value: dict | None):
        if value is None:
            self.qs.remove("deploy_profile")
        else:
            self.qs.setValue("deploy_profile",
                             base64.b64encode(json.dumps(value).encode()).decode())
        self.qs.sync()
