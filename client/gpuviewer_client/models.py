"""客户端数据结构：环形缓冲、LRU、虚拟化表格模型、告警状态机。"""
import collections

import numpy as np
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt


class RingBuffer:
    def __init__(self, capacity: int):
        self.capacity = capacity
        self._ts = np.zeros(capacity)
        self._v = np.zeros(capacity)
        self._n = 0
        self._i = 0

    def append(self, ts: float, v: float) -> None:
        self._ts[self._i] = ts
        self._v[self._i] = v
        self._i = (self._i + 1) % self.capacity
        self._n = min(self._n + 1, self.capacity)

    def arrays(self):
        if self._n < self.capacity:
            return self._ts[: self._n].copy(), self._v[: self._n].copy()
        idx = np.roll(np.arange(self.capacity), -self._i)
        return self._ts[idx].copy(), self._v[idx].copy()


class LRUCache:
    def __init__(self, capacity: int):
        self.capacity = capacity
        self._d: collections.OrderedDict = collections.OrderedDict()

    def get(self, key):
        if key in self._d:
            self._d.move_to_end(key)
            return self._d[key]
        return None

    def put(self, key, value) -> None:
        self._d[key] = value
        self._d.move_to_end(key)
        if len(self._d) > self.capacity:
            self._d.popitem(last=False)


class ProcessTableModel(QAbstractTableModel):
    def __init__(self, headers: list[str], rows=None, parent=None):
        super().__init__(parent)
        self._headers = headers
        self._rows: list[tuple] = list(rows or [])

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return len(self._headers)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        if role in (Qt.DisplayRole, Qt.ToolTipRole):
            try:
                return str(self._rows[index.row()][index.column()])
            except IndexError:
                return None
        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self._headers[section]
        return None

    def set_rows(self, rows: list[tuple]) -> None:
        if len(rows) != len(self._rows):
            self.beginResetModel()
            self._rows = list(rows)
            self.endResetModel()
            return
        changed = [i for i, (a, b) in enumerate(zip(self._rows, rows)) if a != b]
        self._rows = list(rows)
        if changed:
            self.dataChanged.emit(self.index(min(changed), 0),
                                  self.index(max(changed), len(self._headers) - 1))


class AlertEngine:
    """跨快照的边沿检测：离线↔恢复、磁盘%/GPU温度 超阈值穿越。"""

    def __init__(self):
        self._offline: dict[str, bool] = {}
        self._disk_hot: dict[str, bool] = {}
        self._gpu_hot: dict[str, bool] = {}

    def evaluate(self, states: list[dict], disk_warn_pct: float,
                 gpu_temp_warn: float) -> list[dict]:
        import time
        events = []
        now = time.time()
        seen = set()
        for st in states:
            sid = st["id"]
            seen.add(sid)
            was_off = self._offline.get(sid, False)
            is_off = st["status"] == "offline"
            if is_off and not was_off:
                events.append({"ts": now, "server": sid, "kind": "offline",
                               "level": "error",
                               "message": "%s 已失联：%s" % (st["name"], st.get("last_error"))})
            if not is_off and was_off:
                events.append({"ts": now, "server": sid, "kind": "online",
                               "level": "info", "message": "%s 已恢复在线" % st["name"]})
            self._offline[sid] = is_off
            snap = st.get("snapshot") or {}
            for d in snap.get("disks", []):
                key = "%s|%s" % (sid, d.get("mount"))
                hot = d.get("pct", 0) >= disk_warn_pct
                if hot and not self._disk_hot.get(key, False):
                    events.append({"ts": now, "server": sid, "kind": "disk_warn",
                                   "level": "warning",
                                   "message": "%s:%s 磁盘使用率 %.1f%%" % (
                                       st["name"], d.get("mount"), d.get("pct", 0))})
                self._disk_hot[key] = hot
            for g in snap.get("gpus", []):
                key = "%s|%s" % (sid, g.get("index"))
                hot = (g.get("temperature") or 0) >= gpu_temp_warn
                if hot and not self._gpu_hot.get(key, False):
                    events.append({"ts": now, "server": sid, "kind": "gpu_temp_warn",
                                   "level": "warning",
                                   "message": "%s GPU%d 温度 %.0f℃" % (
                                       st["name"], g.get("index", 0), g.get("temperature", 0))})
                self._gpu_hot[key] = hot
        for sid in list(self._offline):
            if sid not in seen:
                del self._offline[sid]
        return events
