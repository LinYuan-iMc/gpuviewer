"""HTTP 线程：Poller 周期拉全量快照；HistoryFetcher 按需拉历史。

ApiCall/crud_call：一次性管理面 REST（servers 增删改查），跑在 QThread 里
避免阻塞 UI（同 Poller 模式）。
"""
import requests
from PySide6.QtCore import QThread, Signal


class Poller(QThread):
    snapshot_ready = Signal(object)
    error = Signal(str)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self._s = settings
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        url = self._s.base_url.rstrip("/") + "/api/snapshot"
        headers = {"Authorization": "Bearer " + self._s.token}
        while not self._stop:
            try:
                r = requests.get(url, headers=headers, timeout=3)
                r.raise_for_status()
                self.snapshot_ready.emit(r.json())
            except Exception as e:                      # noqa: BLE001
                self.error.emit(str(e))
            for _ in range(int(self._s.interval_s * 10)):
                if self._stop:
                    return
                self.msleep(100)


class HistoryFetcher(QThread):
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, base_url, token, server_id, keys, t_from, t_to,
                 max_points=500, parent=None):
        super().__init__(parent)
        self._url = (base_url.rstrip("/") + "/api/servers/%s/history" % server_id)
        self._headers = {"Authorization": "Bearer " + token}
        self._params = {"keys": ",".join(keys), "from": t_from, "to": t_to,
                        "max_points": max_points}

    def run(self):
        try:
            r = requests.get(self._url, headers=self._headers,
                             params=self._params, timeout=30)
            r.raise_for_status()
            self.done.emit(r.json())
        except Exception as e:                          # noqa: BLE001
            self.failed.emit(str(e))


def crud_call(settings, method: str, path: str, json_body=None):
    """同步管理面 REST 调用；由 ApiCall 包进线程跑。异常文本直接给 UI 展示。"""
    r = requests.request(method, settings.base_url.rstrip("/") + path,
                         headers={"Authorization": "Bearer " + settings.token},
                         json=json_body, timeout=8)
    if r.status_code >= 400:
        detail = ""
        try:
            detail = r.json().get("detail", "")
        except Exception:                                    # noqa: BLE001
            pass
        raise RuntimeError(f"HTTP {r.status_code}：{detail or r.reason}")
    return r.json() if r.content else None


class ApiCall(QThread):
    """一次性 REST 调用线程（servers 增删改查等）。"""
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self._fn = fn

    def run(self):
        try:
            self.done.emit(self._fn())
        except Exception as e:                               # noqa: BLE001
            self.failed.emit(str(e))
