"""总览页：每台服务器一张全宽紧凑横条卡（摘要行 + GPU 迷你块排）。

密度基准：单卡高 ~64px 的 GPU 块一行排开（nvitop 风格），
摘要行高 26px，整卡 ~110px，两台机器同屏无滚动。
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from gpuviewer_client.ui.widgets import (
    Dot,
    GlassCard,
    GpuChip,
    MiniBar,
    Sparkline,
    _styled,
    section_title,
)


def fmt_bytes(n, digits=1):
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if n < 1024 or unit == "PB":
            return "%.*f %s" % (digits, n, unit)
        n /= 1024.0
    return "%.1f PB" % n


def fmt_uptime(sec):
    sec = float(sec or 0)
    if sec >= 86400:
        return "%.1f 天" % (sec / 86400.0)
    if sec >= 3600:
        return "%.1f 时" % (sec / 3600.0)
    return "%.0f 分" % (sec / 60.0)


class _KV(QWidget):
    """行内 key-value：返回可更新 value 标签。"""

    def __init__(self, label: str, value_color="text"):
        super().__init__()
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(4)
        h.addWidget(_styled(QLabel(label), "sub", 10))
        self.value = _styled(QLabel("--"), value_color, 11, mono=True, bold=True)
        h.addWidget(self.value)


class ServerCard(GlassCard):
    """紧凑横条卡：第一行摘要，第二行 GPU 块。"""

    clicked = Signal(str)

    def __init__(self, server_id: str, parent=None):
        super().__init__(radius=14, hoverable=True)
        self.server_id = server_id
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(160)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 7, 10, 7)
        lay.setSpacing(3)

        # ---- 摘要行 ----
        head = QHBoxLayout()
        head.setSpacing(8)
        self.dot = Dot()
        self.name_label = _styled(QLabel(""), "text", 14, bold=True)
        self.meta_label = _styled(QLabel(""), "sub", 10)
        head.addWidget(self.dot)
        head.addWidget(self.name_label)
        head.addWidget(self.meta_label)
        head.addStretch(1)
        self.cpu_kv = _KV("CPU")
        self.cpu_bar = MiniBar()
        self.cpu_bar.setFixedWidth(52)
        self.mem_kv = _KV("内存")
        self.mem_bar = MiniBar()
        self.mem_bar.setFixedWidth(52)
        self.disk_label = _styled(QLabel(""), "sub", 10, mono=True)
        head.addWidget(self.cpu_kv)
        head.addWidget(self.cpu_bar)
        head.addSpacing(8)
        head.addWidget(self.mem_kv)
        head.addWidget(self.mem_bar)
        head.addSpacing(8)
        head.addWidget(self.disk_label)
        lay.addLayout(head)

        # ---- 趋势行：CPU 与 GPU 峰值 sparkline（最近 ~10 分钟，5s 一点）----
        trend = QHBoxLayout()
        trend.setSpacing(10)
        self.cpu_spark = Sparkline(capacity=600, color="#58a6ff")
        self.gpu_spark = Sparkline(capacity=600, color="#8957e5")
        for sp, lab in ((self.cpu_spark, "CPU"), (self.gpu_spark, "GPU 峰值")):
            box = QVBoxLayout()
            box.setSpacing(0)
            cap = _styled(QLabel(lab), "sub", 8)
            box.addWidget(cap)
            box.addWidget(sp, 1)
            trend.addLayout(box, 1)
        lay.addLayout(trend)

        # ---- GPU 行 ----
        self.gpu_host = QHBoxLayout()
        self.gpu_host.setSpacing(4)
        lay.addLayout(self.gpu_host, 1)
        self.gpu_chips: list[GpuChip] = []

    def _styled_disk(self, color_key):
        self.disk_label.setStyleSheet(
            "color:%s; font-size:10pt; font-family:Consolas, monospace"
            % {"warn": "#d29922", "error": "#f85149", "ok": "#9aa4b2"}[color_key])

    def update_state(self, state: dict, disk_warn: float):
        snap = state.get("snapshot") or {}
        status = state["status"]
        self.name_label.setText(state["name"])
        self.dot.set_color({"online": "normal", "degraded": "warning",
                            "offline": "offline"}.get(status, "offline"))
        host = snap.get("host", {}) or {}
        cpu = snap.get("cpu", {}) or {}
        self.meta_label.setText("%s · %d 核 · 开机 %s" % (
            host.get("os_release", "") or "—",
            cpu.get("cores", 0), fmt_uptime(host.get("uptime_s"))))
        self.meta_label.setToolTip(self.meta_label.text())   # 窄窗截断时悬浮全文
        util = cpu.get("utilization_total")
        self.cpu_bar.set_value(util)
        self.cpu_kv.value.setText("%s%%" % ("--" if util is None else "%.0f" % util))
        mem = snap.get("memory", {}) or {}
        mem_pct = (mem.get("used", 0) * 100.0 / mem["total"]) if mem.get("total") else 0.0
        self.mem_bar.set_value(mem_pct if mem.get("total") else None)
        self.mem_kv.value.setText(
            fmt_bytes(mem.get("used"), 0).replace(" B", "B").replace(" KB", "K")
            .replace(" MB", "M").replace(" GB", "G").replace(" TB", "T")
            if mem.get("total") else "--")
        disks = snap.get("disks", [])
        if disks:
            worst = max(disks, key=lambda d: d.get("pct", 0))
            self.disk_label.setText("磁盘 %s %.0f%%" % (worst["mount"], worst["pct"]))
            self.disk_label.setToolTip("使用率最高的挂载点：%s %.1f%%" % (
                worst["mount"], worst["pct"]))
            self._styled_disk("error" if worst["pct"] >= disk_warn else
                              ("warn" if worst["pct"] >= disk_warn - 5 else "ok"))
        gpus = snap.get("gpus", [])
        while len(self.gpu_chips) < len(gpus):
            chip = GpuChip()
            self.gpu_chips.append(chip)
            self.gpu_host.addWidget(chip)
        for chip, g in zip(self.gpu_chips, gpus):
            chip.update_gpu(g)
        # 趋势：CPU 总量 + GPU 峰值（离线不推进——平台段即失联时段）
        gpu_peak = max((g.get("utilization") or 0 for g in gpus), default=0)
        self.cpu_spark.push(cpu.get("utilization_total"))
        self.gpu_spark.push(gpu_peak if gpus else None)

    def mouseReleaseEvent(self, _):
        self.clicked.emit(self.server_id)

    def click(self):
        self.clicked.emit(self.server_id)


class OverviewPage(QScrollArea):
    server_clicked = Signal(str)

    def __init__(self, disk_warn_pct: float | None = None, parent=None):
        super().__init__(parent)
        self._disk_warn_pct = disk_warn_pct   # None=跟随 AppSettings（生产）；测试注入定值
        self._cards: dict[str, ServerCard] = {}
        self._host = QWidget()
        self._vbox = QVBoxLayout(self._host)
        self._vbox.setContentsMargins(10, 10, 10, 10)
        self._vbox.setSpacing(8)
        self._vbox.addWidget(section_title("服务器总览"))   # 顶置（用户要求）
        self._vbox.addStretch(1)
        self.setWidget(self._host)
        self.setWidgetResizable(True)

    def update_snapshot(self, servers: list[dict]):
        alive = {st["id"] for st in servers}
        for sid in list(self._cards):            # 回收快照中消失的卡片（同侧栏同步）
            if sid not in alive:
                card = self._cards.pop(sid)
                card.setParent(None)
                card.deleteLater()
        for st in servers:
            sid = st["id"]
            if sid not in self._cards:
                card = ServerCard(sid)
                card.clicked.connect(self.server_clicked.emit)
                self._cards[sid] = card
                self._vbox.insertWidget(self._vbox.count() - 1, card)  # 排在 stretch 前
            self._cards[sid].update_state(st, self._disk_warn())
        self._host.setMinimumSize(self._host.sizeHint())

    def _disk_warn(self):
        if self._disk_warn_pct is not None:
            return self._disk_warn_pct
        from gpuviewer_client.settings import AppSettings
        return AppSettings().disk_warn_pct

    def card_names(self):
        return [c.name_label.text() for c in self._cards.values()]
