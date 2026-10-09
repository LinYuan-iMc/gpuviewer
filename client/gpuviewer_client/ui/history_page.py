"""历史趋势页 v2：友好图例 + 全 GPU 曲线 + 人类可读时间轴 + 统一缩放。

交互约定：
  - 普通滚轮 → 滚动页面（图表不吞事件）；
  - Ctrl+滚轮 → 所有图表 X 轴以光标为中心同步缩放（联动）；
  - 双击图表 → 进入该指标的大图详情（ChartDetailDialog）：
      滚轮=左右平移时间轴 · Ctrl+滚轮=缩放 · 双击=复位 · Esc/按钮=返回。
"""
import time

import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QLinearGradient, QWheelEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from gpuviewer_client.api_client import HistoryFetcher
from gpuviewer_client.models import LRUCache


class _DialogPlot(pg.PlotWidget):
    """大图弹窗专用：滚轮平移 / Ctrl+滚轮缩放 / 双击复位。

    滚轮必须拦在 PlotWidget 层——pyqtgraph 的 ViewBox 会吞掉滚轮事件
    （mouseEnabled 全关时表现为空操作 accept），写在 QDialog 上永远收不到。"""

    def __init__(self, dialog: "ChartDetailDialog", title: str, parent=None):
        axis = pg.DateAxisItem(orientation="bottom")
        super().__init__(axisItems={"bottom": axis}, parent=parent)
        self._dlg = dialog
        self._title = title
        self.getPlotItem().setMouseEnabled(x=False, y=False)
        self.getViewBox().setMenuEnabled(False)

    def wheelEvent(self, ev: QWheelEvent):
        ev.accept()
        self._dlg.handle_wheel(ev, self)

    def mouseDoubleClickEvent(self, ev):
        ev.accept()
        self._dlg._reset_view()


class ChartDetailDialog(QDialog):
    """单指标大图：滚轮平移 · Ctrl+滚轮缩放 · 双击复位 · Esc 返回。"""

    def __init__(self, title: str, series: dict[str, tuple], parent=None):
        """series: {key: (ts_list, vs_list, color, friendly)}"""
        super().__init__(parent)
        self.setWindowTitle("%s · 大图" % title)
        self.resize(1080, 620)
        self.setStyleSheet(
            "QDialog { background: rgba(16,19,25,245); }"
            "QLabel { color:#e8eaed; background:transparent; }"
            "QPushButton { color:#e8eaed; background:rgba(35,40,50,160);"
            " border:1px solid rgba(255,255,255,26); border-radius:8px;"
            " padding:6px 16px; }")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(6)
        head = QHBoxLayout()
        lab = QLabel("%s" % title)
        lab.setStyleSheet("font-size:14pt; font-weight:600;")
        head.addWidget(lab)
        head.addStretch(1)
        hint = QLabel("滚轮 平移 · Ctrl+滚轮 缩放 · 双击 复位")
        hint.setStyleSheet("color:#9aa4b2;")
        head.addWidget(hint)
        close = QPushButton("返回 ✕")
        close.clicked.connect(self.accept)
        head.addWidget(close)
        lay.addLayout(head)

        self.plot = _DialogPlot(self, title)
        self.plot.getViewBox().setMenuEnabled(False)
        self.plot.showGrid(x=True, y=True, alpha=0.2)
        # 不用 clipToView/autoDownsample：服务端已按 max_points 降采样（≤1800 点/线），
        # 本地裁剪反而在"窄视窗 setData → 扩大视窗"时让曲线滞留旧窗（7d 前段空白的真凶）
        self.plot.setLabel("left", title)
        self._full_range = None
        n = len(series)
        for i, (k, (ts, vs, color, friendly)) in enumerate(sorted(series.items())):
            kw = {"pen": pg.mkPen(color, width=1.8)}
            if n <= 2:
                grad = QLinearGradient(0, 0, 0, 1)
                grad.setCoordinateMode(QLinearGradient.ObjectBoundingMode)
                c0, c1 = QColor(color), QColor(color)
                c0.setAlpha(90)
                c1.setAlpha(0)
                grad.setColorAt(0.0, c0)
                grad.setColorAt(1.0, c1)
                kw.update(fillLevel=0, brush=QBrush(grad))
            self.plot.plot(ts, vs, name=friendly, **kw)
            if ts:
                lo, hi = min(ts), max(ts)
                self._full_range = (min(lo, self._full_range[0]),
                                    max(hi, self._full_range[1])) \
                    if self._full_range else (lo, hi)
        if n > 1:
            self.plot.addLegend(offset=(12, 12), labelTextColor="#9aa4b2")
        self.plot.enableAutoRange(y=True)
        lay.addWidget(self.plot, 1)
        if self._full_range:
            self._reset_view()

    def _reset_view(self):
        if self._full_range:
            self.plot.getPlotItem().getViewBox().setXRange(
                self._full_range[0], self._full_range[1], padding=0.02)

    def handle_wheel(self, ev: QWheelEvent, plot: pg.PlotWidget):
        """滚轮平移 / Ctrl+滚轮缩放（锚点=光标时间，正确的场景坐标换算）。"""
        vb = plot.getPlotItem().getViewBox()
        (x0, x1), _ = vb.viewRange()
        span = x1 - x0
        if ev.modifiers() & Qt.ControlModifier:
            factor = 1.25 if ev.angleDelta().y() > 0 else 0.8
            new_span = span / factor
            if self._full_range:
                new_span = min(new_span, self._full_range[1] - self._full_range[0])
            anchor = (x0 + x1) / 2.0
            try:
                view_pos = vb.mapSceneToView(plot.mapToScene(ev.position().toPoint()))
                if x0 - span <= view_pos.x() <= x1 + span:
                    anchor = view_pos.x()
            except Exception:
                pass
            vb.setXRange(anchor - new_span / 2, anchor + new_span / 2, padding=0)
        else:                                   # 普通滚轮：左右平移时间轴
            step = span * 0.08 * (1 if ev.angleDelta().y() < 0 else -1)
            vb.setXRange(x0 + step, x1 + step, padding=0)

    def wheelEvent(self, ev: QWheelEvent):
        ev.accept()
        self.handle_wheel(ev, self.plot)

    def mouseDoubleClickEvent(self, ev):
        ev.accept()
        self._reset_view()

RANGES = [("1h", 1), ("6h", 6), ("24h", 24), ("7d", 168)]
NET_TITLE = "网络 MB/s"
# (标题, 键模板, 单位换算)——GPU 类键用 {i} 展开为每块卡一条曲线
CHARTS = [
    ("CPU 利用率 %", ["cpu_total"], {}),
    ("内存使用 GB", ["mem_used"], {"mem_used": 1.0 / 2 ** 30}),
    ("GPU 利用率 %", ["gpu:{i}.util"], {}),
    ("GPU 显存 GB", ["gpu:{i}.mem_used"], {"gpu:{i}.mem_used": 1.0 / 2 ** 10}),
    ("GPU 温度 ℃", ["gpu:{i}.temp"], {}),
    ("GPU 功耗 W", ["gpu:{i}.power_draw"], {}),
    (NET_TITLE, None, {"net": 1.0 / 2 ** 20}),     # net 键动态生成
]
_PENS = ["#58a6ff", "#3fb950", "#d29922", "#f85149", "#bc8cff",
         "#39c5cf", "#ff7b72", "#e3b341"]


def _friendly(k: str) -> str:
    """机器键 → 图例友好名：gpu:3.mem_used→GPU3；net:eno1.rx→eno1 接收。"""
    if k.startswith("gpu:"):
        return "GPU" + k.split(":", 1)[1].split(".", 1)[0]
    if k.startswith("net:"):
        iface, direction = k[len("net:"):].rsplit(".", 1)
        return "%s %s" % (iface, "接收" if direction == "rx" else "发送")
    if k == "cpu_total":
        return "CPU"
    if k == "mem_used":
        return "已用内存"
    return k


class _LinkedPlot(pg.PlotWidget):
    """禁用 pyqtgraph 默认鼠标。交互：单击进大图（260ms 延迟判定，
    双击则取消并复位——否则双击的第一下 press 会先弹出大图）。"""

    ctrl_zoom = Signal(object)      # QWheelEvent
    reset_all = Signal()
    open_detail = Signal(str)       # 图表标题（单击进入大图）

    def __init__(self, parent=None):
        axis = pg.DateAxisItem(orientation="bottom")
        super().__init__(axisItems={"bottom": axis}, parent=parent)
        self._title = ""
        self._open_timer = QTimer(self)
        self._open_timer.setSingleShot(True)
        self._open_timer.setInterval(260)
        self._open_timer.timeout.connect(self._fire_open)
        pi = self.getPlotItem()
        pi.setMouseEnabled(x=False, y=False)
        pi.getViewBox().setMenuEnabled(False)
        pi.showGrid(x=True, y=True, alpha=0.2)
        # 同 ChartDetailDialog：禁用 clipToView/autoDownsample（视窗切换曲线滞留 bug 源）

    def set_chart_title(self, title: str):
        self._title = title

    def _fire_open(self):
        self.open_detail.emit(self._title)

    def wheelEvent(self, ev: QWheelEvent):
        if ev.modifiers() & Qt.ControlModifier:
            ev.accept()
            self.ctrl_zoom.emit(ev)
        else:
            ev.ignore()             # 让 QScrollArea 滚动页面

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            ev.accept()
            self._open_timer.start()            # 260ms 内无第二击才进大图
        else:
            super().mousePressEvent(ev)

    def mouseDoubleClickEvent(self, ev):
        ev.accept()
        self._open_timer.stop()                 # 取消待发的"进大图"
        self.reset_all.emit()


class _LegendRow(QWidget):
    """可交互图例行：悬停=高亮该曲线，点击=独显/恢复。"""

    hovered = Signal(str)      # key
    unhovered = Signal()
    toggled = Signal(str)      # key

    def __init__(self, key: str, name: str, color: str, stats: str = "",
                 parent=None):
        super().__init__(parent)
        self.key = key
        self.setFixedHeight(22)
        self.setCursor(Qt.PointingHandCursor)
        tip = ("%s\n%s\n（悬停高亮 · 点击独显/恢复）" % (name, stats)
               if stats else "%s（悬停高亮，点击独显/恢复）" % name)
        self.setToolTip(tip)
        h = QHBoxLayout(self)
        h.setContentsMargins(4, 2, 4, 2)
        h.setSpacing(5)
        sw = QFrame()
        sw.setFixedSize(8, 8)
        sw.setStyleSheet("background:%s; border:none;border-radius:2px;" % color)
        self.label = QLabel(name)
        self.label.setStyleSheet("color:#9aa4b2; font-size:9pt; background:transparent;")
        h.addWidget(sw)
        h.addWidget(self.label)
        h.addStretch(1)
        self._normal_ss = "background:transparent; border-radius:5px;"
        self._hot_ss = "background:rgba(255,255,255,22); border-radius:5px;"
        self.setStyleSheet(self._normal_ss)

    def enterEvent(self, e):
        self.setStyleSheet(self._hot_ss)
        self.label.setStyleSheet("color:#e8eaed; font-size:9pt; background:transparent;")
        self.hovered.emit(self.key)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.setStyleSheet(self._normal_ss)
        self.label.setStyleSheet("color:#9aa4b2; font-size:9pt; background:transparent;")
        self.unhovered.emit()
        super().leaveEvent(e)

    def mouseReleaseEvent(self, e):
        self.toggled.emit(self.key)


class _LegendColumn(QWidget):
    """绘图区右侧的自绘图例：悬停高亮 / 点击独显单条曲线。"""

    hovered = Signal(str)
    unhovered = Signal()
    toggled = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(6, 2, 2, 2)
        self._lay.setSpacing(1)

    def set_items(self, items: list[tuple[str, str]]):
        while self._lay.count():
            item = self._lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for entry in items:
            key, name, color = entry[0], entry[1], entry[2]
            stats = entry[3] if len(entry) > 3 else ""
            row = _LegendRow(key, name, color, stats)
            row.hovered.connect(self.hovered.emit)
            row.unhovered.connect(self.unhovered.emit)
            row.toggled.connect(self.toggled.emit)
            self._lay.addWidget(row)


class HistoryPage(QScrollArea):
    """页栈第三页：跟随侧栏当前服务器；范围按钮 + 七类趋势图（全 GPU）。"""

    back_requested = Signal()

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self._s = settings
        self._cache = LRUCache(8)
        self._cache_ts: dict = {}           # 仅对真实拉取记录时间（60 秒过期）
        self._server_id = None
        self._server_name = ""
        self._hours = 1.0
        self._fetching = None
        self._ifaces: list[str] = ["eth0"]  # 收到快照前的回退
        self._gpu_n = 0                     # 各机最大 GPU 数（快照驱动）
        # TensorBoard 三件套状态：平滑系数 / 序列可见性 / 最近载荷
        self._smooth = 0.0                  # 0=关闭；>0 时原始线淡化+EMA主线
        self._enabled_gpus: set[int] = set()    # 空=全部可见
        self._enabled_ifaces: set[str] = set()
        self._last_payload: dict | None = None
        pg.setConfigOptions(antialias=False)         # 性能优先（uPlot 范式：AA 是多曲线重绘头号开销）
        pg.setConfigOption("background", pg.mkColor(0, 0, 0, 0))   # 透明底透出毛玻璃
        pg.setConfigOption("foreground", pg.mkColor(154, 164, 178))

        # ---- 顶栏：返回 | 标题 | 范围 | 平滑滑杆 | 提示 ----
        bar = QHBoxLayout()
        self.back_btn = QPushButton("返回详情")
        self.back_btn.clicked.connect(self.back_requested.emit)
        bar.addWidget(self.back_btn)
        self.title_label = QLabel("")
        self.title_label.setStyleSheet(
            "color:#e8eaed; font-size:14pt; font-weight:600;")
        bar.addSpacing(10)
        bar.addWidget(self.title_label)
        bar.addSpacing(10)
        self._range_btns: dict[str, QPushButton] = {}
        for label, h in RANGES:
            b = QPushButton(label)
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, hh=h: self._set_range(hh))
            self._range_btns[label] = b
            bar.addWidget(b)
        bar.addStretch(1)
        smooth_lab = QLabel("平滑")
        smooth_lab.setStyleSheet("color:#9aa4b2;")
        self.smooth_slider = QSlider(Qt.Horizontal)
        self.smooth_slider.setRange(0, 95)
        self.smooth_slider.setValue(0)
        self.smooth_slider.setFixedWidth(110)
        self._smooth_timer = QTimer(self)
        self._smooth_timer.setSingleShot(True)
        self._smooth_timer.setInterval(120)
        self._smooth_timer.timeout.connect(self._apply_smooth)
        self.smooth_slider.valueChanged.connect(
            lambda _v: self._smooth_timer.start())   # 防抖：拖动中不反复全量重绘
        self.smooth_value = QLabel("关")
        self.smooth_value.setStyleSheet(
            "color:#9aa4b2; font-family:Consolas,monospace;")
        self.smooth_value.setFixedWidth(34)
        bar.addWidget(smooth_lab)
        bar.addWidget(self.smooth_slider)
        bar.addWidget(self.smooth_value)
        bar.addSpacing(8)
        bar.addWidget(QLabel("单击 大图 · 双击 复位 · Ctrl+滚轮 缩放",
                             objectName="sub"))
        self._set_checked_range("1h")

        # ---- 左侧：序列选择器（TensorBoard Runs 面板范式） ----
        side = QWidget()
        side.setFixedWidth(168)
        side.setStyleSheet("background:rgba(14,17,23,96); border-radius:10px;")
        sv = QVBoxLayout(side)
        sv.setContentsMargins(8, 8, 8, 8)
        sv.setSpacing(4)
        sel_title = QLabel("序列")
        sel_title.setStyleSheet(
            "color:#9aa4b2; font-size:9pt; font-weight:700; letter-spacing:2px;")
        sv.addWidget(sel_title)
        sel_btns = QHBoxLayout()
        b_all = QPushButton("全选")
        b_none = QPushButton("清空")
        for b in (b_all, b_none):
            b.setStyleSheet("padding:2px 8px;")
        b_all.clicked.connect(lambda: self._set_all_series(True))
        b_none.clicked.connect(lambda: self._set_all_series(False))
        sel_btns.addWidget(b_all)
        sel_btns.addWidget(b_none)
        sv.addLayout(sel_btns)
        self._gpu_checks_host = QWidget()
        self._gpu_checks_lay = QVBoxLayout(self._gpu_checks_host)
        self._gpu_checks_lay.setContentsMargins(0, 2, 0, 2)
        self._gpu_checks_lay.setSpacing(1)
        sv.addWidget(self._gpu_checks_host)
        net_title = QLabel("网卡")
        net_title.setStyleSheet(
            "color:#9aa4b2; font-size:9pt; font-weight:700; letter-spacing:2px;")
        sv.addWidget(net_title)
        self._net_checks_host = QWidget()
        self._net_checks_lay = QVBoxLayout(self._net_checks_host)
        self._net_checks_lay.setContentsMargins(0, 2, 0, 2)
        self._net_checks_lay.setSpacing(1)
        sv.addWidget(self._net_checks_host)
        sv.addStretch(1)

        # ---- 右侧：工具栏 + 双列卡片网格 ----
        right = QVBoxLayout()
        right.setSpacing(6)
        right.addLayout(bar)
        self._error_label = QLabel("")
        self._error_label.setWordWrap(True)
        self._error_label.hide()
        right.addWidget(self._error_label)
        self._charts_host = QWidget()
        self._charts_lay = QGridLayout(self._charts_host)
        self._charts_lay.setContentsMargins(0, 0, 0, 0)
        self._charts_lay.setSpacing(8)
        right.addWidget(self._charts_host, 1)
        body = QHBoxLayout()
        body.setContentsMargins(10, 8, 10, 10)
        body.setSpacing(8)
        body.addWidget(side)
        body.addLayout(right, 1)
        content = QWidget()
        content.setLayout(body)
        self.setWidget(content)
        self.setWidgetResizable(True)
        self._plots: dict[str, _LinkedPlot] = {}      # 惰性创建
        self._legends: dict[str, _LegendColumn] = {}
        self._cards: dict[str, QWidget] = {}
        self._cross: dict[str, tuple] = {}            # 十字线 + 取值浮层
        self._proxies: list = []                      # 防 GC

    # ------------------------------------------------------------------ 图表
    def _ensure_plots(self):
        if self._plots:
            return
        row = col = 0
        for title, _, _ in CHARTS:
            card = QFrame()
            card.setObjectName("chartcard")
            card.setStyleSheet(
                "QFrame#chartcard { background:rgba(30,35,44,110);"
                " border:1px solid rgba(255,255,255,22); border-radius:10px; }")
            cv = QVBoxLayout(card)
            cv.setContentsMargins(8, 4, 8, 6)
            cv.setSpacing(2)
            head = QHBoxLayout()
            head.setSpacing(4)
            t_lab = QLabel(title)
            t_lab.setStyleSheet(
                "color:#9aa4b2; font-size:9pt; font-weight:700;"
                " letter-spacing:1px; background:transparent;")
            head.addWidget(t_lab)
            head.addStretch(1)
            fs_btn = QPushButton("全屏")
            fs_btn.setFixedSize(38, 18)
            fs_btn.setToolTip("放大查看（滚轮平移 / Ctrl+滚轮缩放 / 双击复位）")
            fs_btn.setStyleSheet(
                "QPushButton{border:1px solid rgba(255,255,255,26);"
                "border-radius:4px;background:transparent;"
                " color:#9aa4b2; font-size:8pt;}"
                "QPushButton:hover{background:rgba(255,255,255,26);color:#e8eaed;}")
            fs_btn.clicked.connect(lambda _=False, t=title: self._open_chart_detail(t))
            head.addWidget(fs_btn)
            cv.addLayout(head)
            prow = QWidget()
            h = QHBoxLayout(prow)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(4)
            plot = _LinkedPlot()
            plot.setMinimumHeight(150)
            plot.setMaximumHeight(185)
            plot.set_chart_title(title)
            plot.setLabel("left", title)
            plot.ctrl_zoom.connect(self._on_ctrl_zoom)
            plot.reset_all.connect(self._on_reset)
            plot.open_detail.connect(self._open_chart_detail)
            legend = _LegendColumn()
            legend.hovered.connect(
                lambda k, t=title: self._set_emphasis(t, k, hover=True))
            legend.unhovered.connect(
                lambda t=title: self._set_emphasis(t, None, hover=True))
            legend.toggled.connect(lambda k, t=title: self._toggle_solo(t, k))
            h.addWidget(plot, 1)
            h.addWidget(legend)
            cv.addWidget(prow, 1)
            # 十字线取值（TensorBoard tooltip 范式）
            vline = pg.InfiniteLine(angle=90, movable=False,
                                    pen=pg.mkPen(255, 255, 255, 70, width=1))
            vline.hide()
            plot.addItem(vline, ignoreBounds=True)
            tip = pg.TextItem(anchor=(0, 0), border=pg.mkPen(60, 70, 85, 200),
                              fill=pg.mkColor(16, 19, 25, 225))
            tip.setZValue(100)
            tip.hide()
            plot.addItem(tip, ignoreBounds=True)
            self._cross[title] = (vline, tip)
            proxy = pg.SignalProxy(plot.scene().sigMouseMoved, rateLimit=60,
                                   slot=lambda evt, t=title: self._on_hover(t, evt[0]))
            self._proxies.append(proxy)
            self._plots[title] = plot
            self._legends[title] = legend
            self._cards[title] = card
            if title == NET_TITLE:
                self._charts_lay.addWidget(card, row, 0, 1, 2)   # 网络占整行
                row += 1
                col = 0
            else:
                self._charts_lay.addWidget(card, row, col)
                if col == 1:
                    row += 1
                    col = 0
                else:
                    col = 1
        plots = list(self._plots.values())
        for p in plots[1:]:                       # X 轴全联动
            p.setXLink(plots[0])

    @property
    def hours(self) -> float:
        return self._hours

    def plot_count(self) -> int:
        return len(self._plots)

    # ------------------------------------------------------------------ 数据源
    def set_servers(self, servers: list[dict]):
        ifaces: list[str] = []
        names = {s["id"]: s["name"] for s in servers}
        gpu_n = 0
        for s in servers:
            snap = s.get("snapshot") or {}
            for i in snap.get("net") or []:
                if i.get("name") and i["name"] not in ifaces:
                    ifaces.append(i["name"])
            gpu_n = max(gpu_n, len(snap.get("gpus") or []))
        if ifaces:
            self._ifaces = ifaces
        if gpu_n:
            self._gpu_n = gpu_n
        signature = (gpu_n, tuple(self._ifaces))
        if signature != getattr(self, "_selector_sig", None):
            self._selector_sig = signature
            self._rebuild_selector()      # 仅元数据变化时重建（每 5s 轮询不再抖动）
        if self._server_id in names:
            self.title_label.setText("%s · 历史趋势" % names[self._server_id])

    def _set_checked_range(self, label: str):
        for k, b in self._range_btns.items():
            b.setChecked(k == label)

    def _set_range(self, hours: float):
        label = next((lbl for lbl, h in RANGES if h == hours), "1h")
        self._set_checked_range(label)
        if self._server_id:
            self.show_history(self._server_id, hours)

    def _net_keys(self) -> list[str]:
        out = []
        for name in self._ifaces:
            out += ["net:%s.rx" % name, "net:%s.tx" % name]
        return out

    def _keys_for_title(self, title: str) -> list[str]:
        for t, tmpl, _ in CHARTS:
            if t != title:
                continue
            if t == NET_TITLE:
                return self._net_keys()
            keys = []
            for k in tmpl:
                if "{i}" in k:
                    keys += [k.format(i=i) for i in range(max(self._gpu_n, 1))]
                else:
                    keys.append(k)
            return keys
        return []

    def _keys(self) -> list[str]:
        keys = []
        for title, _, _ in CHARTS:
            keys += self._keys_for_title(title)
        return keys

    # ------------------------------------------------------------------ 拉取
    def _cached(self, key):
        entry = self._cache.get(key)
        if entry is None:
            return None
        ts = self._cache_ts.get(key)
        if ts is not None and time.time() - ts >= 60:
            return None                          # 条目 60 秒过期
        return entry

    def show_history(self, server_id: str, hours: float):
        self._ensure_plots()
        if server_id != self._server_id:
            self._server_name = ""               # 由 set_servers/主窗提供显示名
        self._server_id, self._hours = server_id, hours
        key = (server_id, hours)
        cached = self._cached(key)
        if cached is not None:
            self._render(cached)
            return
        if (self._fetching is not None
                and getattr(self._fetching, "key", None) == key
                and getattr(self._fetching, "isRunning", lambda: False)()):
            return
        self._reap_fetcher()                     # 串行化：先收掉在途 fetcher
        now = time.time()
        f = HistoryFetcher(self._s.base_url, self._s.token, server_id,
                           self._keys(), now - hours * 3600, now, max_points=1800)
        f.key = key
        f.done.connect(lambda payload, k=key: self._on_done(k, payload))
        f.failed.connect(self._on_fetch_failed)
        f.start()
        self._fetching = f

    def _on_fetch_failed(self, msg: str):
        self._error_label.setText("历史拉取失败：%s" % msg)
        self._error_label.show()

    def _reap_fetcher(self):
        f, self._fetching = self._fetching, None
        if f is None or not getattr(f, "isRunning", lambda: False)():
            return
        for name in ("done", "failed"):
            sig = getattr(f, name, None)
            if sig is not None and hasattr(sig, "disconnect"):
                sig.disconnect()
        f.wait(6000)

    def _on_done(self, key, payload: dict):
        self._cache.put(key, payload)
        self._cache_ts[key] = time.time()
        if key == (self._server_id, self._hours):
            self._render(payload)

    # ------------------------------------------------------------------ 渲染
    @staticmethod
    def _scale_for(k: str) -> float:
        """按实际键名换算单位（模板键与展开键不同，必须按后缀规则匹配）：
        mem_used 字节→GB；gpu:*.mem_used MiB→GB；net:* B/s→MB/s。"""
        if k == "mem_used":
            return 1.0 / 2 ** 30
        if k.startswith("gpu:") and k.endswith(".mem_used"):
            return 1.0 / 2 ** 10
        if k.startswith("net:"):
            return 1.0 / 2 ** 20
        return 1.0

    # ------------------------------------------------- 平滑 / 选择器（TensorBoard）
    @staticmethod
    def _ema(vs, s):
        """TensorBoard 同款指数滑动平均：out[i]=out[i-1]*s + v[i]*(1-s)。"""
        if not vs:
            return vs
        out = [vs[0]]
        for v in vs[1:]:
            out.append(out[-1] * s + v * (1.0 - s))
        return out

    def _apply_smooth(self):
        value = self.smooth_slider.value()
        self._smooth = value / 100.0
        self.smooth_value.setText("关" if value == 0 else "%.2f" % self._smooth)
        if self._last_payload is not None:
            self._render(self._last_payload)

    def _series_visible(self, k: str) -> bool:
        if k.startswith("gpu:"):
            idx = int(k.split(":", 1)[1].split(".", 1)[0])
            return (not self._enabled_gpus) or (idx in self._enabled_gpus)
        if k.startswith("net:"):
            iface = k[len("net:"):].rsplit(".", 1)[0]
            return (not self._enabled_ifaces) or (iface in self._enabled_ifaces)
        return True

    def _rebuild_selector(self):
        """按 gpu_n/_ifaces 重建左侧复选框（保持既有勾选状态）。"""
        # GPU
        while self._gpu_checks_lay.count():
            it = self._gpu_checks_lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        for i in range(self._gpu_n):
            color = _PENS[i % len(_PENS)]
            cb = QCheckBox("GPU%d" % i)
            cb.setChecked((not self._enabled_gpus) or (i in self._enabled_gpus))
            cb.setStyleSheet(
                "QCheckBox{color:#c9d1d9; font-size:10pt; spacing:6px;"
                " background:transparent;}"
                "QCheckBox::indicator{width:12px;height:12px;border-radius:3px;"
                " border:1px solid %s; background:%s;}" % (color, color))
            cb.toggled.connect(
                lambda on, idx=i: self._toggle_gpu(idx, on))
            self._gpu_checks_lay.addWidget(cb)
        while self._net_checks_lay.count():
            it = self._net_checks_lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        for j, name in enumerate(self._ifaces):
            color = _PENS[(j * 2) % len(_PENS)]
            cb = QCheckBox(name)
            cb.setChecked((not self._enabled_ifaces)
                          or (name in self._enabled_ifaces))
            cb.setStyleSheet(
                "QCheckBox{color:#c9d1d9; font-size:10pt; spacing:6px;"
                " background:transparent;}"
                "QCheckBox::indicator{width:12px;height:12px;border-radius:3px;"
                " border:1px solid %s; background:%s;}" % (color, color))
            cb.toggled.connect(
                lambda on, n=name: self._toggle_iface(n, on))
            self._net_checks_lay.addWidget(cb)

    def _toggle_gpu(self, idx: int, on: bool):
        gpu_all = set(range(self._gpu_n))
        cur = self._enabled_gpus or gpu_all
        cur = (cur | {idx}) if on else (cur - {idx})
        self._enabled_gpus = cur if cur != gpu_all else set()   # 全选=空集（语义=全部）
        self._rebuild_selector()
        if self._last_payload is not None:
            self._render(self._last_payload)

    def _toggle_iface(self, name: str, on: bool):
        all_if = set(self._ifaces)
        cur = self._enabled_ifaces or all_if
        cur = (cur | {name}) if on else (cur - {name})
        self._enabled_ifaces = cur if cur != all_if else set()
        self._rebuild_selector()
        if self._last_payload is not None:
            self._render(self._last_payload)

    def _set_all_series(self, on: bool):
        """全选=空集（语义：不设过滤）；清空=显式排除所有已知索引。"""
        if on:
            self._enabled_gpus = set()
            self._enabled_ifaces = set()
        else:
            self._enabled_gpus = {-1}          # 不可能的索引=全部不可见
            self._enabled_ifaces = {""}
        self._rebuild_selector()
        if self._last_payload is not None:
            self._render(self._last_payload)

    # ------------------------------------------------- 十字线取值（TensorBoard tooltip）
    def _on_hover(self, title: str, scene_pos):
        vline, tip = self._cross.get(title, (None, None))
        plot = self._plots.get(title)
        if vline is None or plot is None:
            return
        vb = plot.getPlotItem().getViewBox()
        if not vb.sceneBoundingRect().contains(scene_pos):
            vline.hide()
            tip.hide()
            return
        x = vb.mapSceneToView(scene_pos).x()
        self._sync_crosshair(title, x)      # 联动：一根竖线同步全部图表
        rows = []
        for k, (ts, vs) in (getattr(self, "_data_map", {}).get(title) or {}).items():
            if not ts or not self._series_visible(k):
                continue
            i = min(range(len(ts)), key=lambda j: abs(ts[j] - x))
            rows.append((vs[i], k))
        if not rows:
            vline.hide()
            tip.hide()
            return
        rows.sort(reverse=True)
        (y0, y1) = vb.viewRange()[1]
        vline.setPos(x)
        vline.show()
        html = "<div style='color:#9aa4b2;font-size:8pt'>%s</div>" % time.strftime(
            "%H:%M:%S", time.localtime(x))
        for v, k in rows[:8]:
            color = (self._curves.get(title) or {}).get(k, (None, "#9aa4b2"))[1]
            html += ("<div style='color:%s;font-size:8pt'>%s&nbsp;"
                     "<span style='color:#e8eaed'>%.2f</span></div>" % (
                         color, _friendly(k), v))
        if len(rows) > 8:
            html += "<div style='color:#6e7681;font-size:8pt'>…共 %d 条</div>" % len(rows)
        tip.setHtml(html)
        tip.setPos(x, y1)
        tip.show()

    def _sync_crosshair(self, source_title: str, x: float):
        """Datadog 范式：来源图悬停，其余图竖线同步（各自浮层独立取值）。"""
        for t_title, (vline, tip) in self._cross.items():
            if t_title == source_title:
                continue
            plot = self._plots.get(t_title)
            if plot is None:
                continue
            vb2 = plot.getPlotItem().getViewBox()
            vline.setPos(x)
            vline.show()
            rows2 = []
            for k, (ts, vs) in (getattr(self, "_data_map", {}).get(t_title)
                                or {}).items():
                if not ts or not self._series_visible(k):
                    continue
                i = min(range(len(ts)), key=lambda j: abs(ts[j] - x))
                rows2.append((vs[i], k))
            if not rows2:
                tip.hide()
                continue
            rows2.sort(reverse=True)
            (y0r, y1r) = vb2.viewRange()[1]
            html = "<div style='color:#9aa4b2;font-size:8pt'>%s</div>" % time.strftime(
                "%H:%M:%S", time.localtime(x))
            for v, k in rows2[:8]:
                color = (self._curves.get(t_title) or {}).get(
                    k, (None, "#9aa4b2"))[1]
                html += ("<div style='color:%s;font-size:8pt'>%s&nbsp;"
                         "<span style='color:#e8eaed'>%.2f</span></div>" % (
                             color, _friendly(k), v))
            if len(rows2) > 8:
                html += ("<div style='color:#6e7681;font-size:8pt'>…共 %d "
                         "条</div>" % len(rows2))
            tip.setHtml(html)
            tip.setPos(x, y1r)
            tip.show()

    # ------------------------------------------------------------------ 渲染
    def _render(self, payload: dict):
        self._ensure_plots()
        self._error_label.clear()
        self._error_label.hide()
        self._last_payload = payload
        data = payload.get("keys", {})
        if not hasattr(self, "_curves"):
            self._curves = {}      # title -> {key: (PlotDataItem, color)}
            self._solo: dict[str, str | None] = {}
            self._hover: dict[str, str | None] = {}
        if not hasattr(self, "_data_map"):
            self._data_map = {}    # title -> {key: (ts, vs)}（十字线取值用）
        for (title, _, _), plot in zip(CHARTS, self._plots.values()):
            plot.clear()
            items = []
            curves: dict[str, tuple] = {}
            data_map: dict[str, tuple] = {}
            any_series = False
            n_visible = len([x for x in self._keys_for_title(title)
                             if data.get(x) and self._series_visible(x)])
            for i, k in enumerate(self._keys_for_title(title)):
                series = data.get(k)
                if not series or not self._series_visible(k):
                    continue
                any_series = True
                scale = self._scale_for(k)
                ts = [p[0] for p in series]
                vs = [p[1] * scale for p in series]
                data_map[k] = (ts, vs)
                color = _PENS[i % len(_PENS)]     # 索引稳定：颜色不随勾选漂移
                main_vs = self._ema(vs, self._smooth) if self._smooth > 0.005 else vs
                if self._smooth > 0.005:          # 原始线淡化 + 平滑主线（TB 范式）
                    c_raw = QColor(color)
                    c_raw.setAlpha(60)
                    plot.plot(ts, vs, pen=pg.mkPen(c_raw, width=1))
                kwargs = {"pen": pg.mkPen(color, width=1.8)}
                if n_visible <= 2:                # 单/双序列：曲线下渐变填充
                    grad = QLinearGradient(0, 0, 0, 1)
                    grad.setCoordinateMode(QLinearGradient.ObjectBoundingMode)
                    c0 = QColor(color)
                    c0.setAlpha(90)
                    c1 = QColor(color)
                    c1.setAlpha(0)
                    grad.setColorAt(0.0, c0)
                    grad.setColorAt(1.0, c1)
                    kwargs.update(fillLevel=0, brush=QBrush(grad))
                item = plot.plot(ts, main_vs, **kwargs)
                curves[k] = (item, color)
                stats = ("当前 %.2f · 区间 %.2f ~ %.2f" % (vs[-1], min(vs), max(vs))
                         if vs else "")
                items.append((k, _friendly(k), color, stats))
            self._curves[title] = curves
            self._data_map[title] = data_map
            legend = self._legends[title]
            if len(items) > 1:                   # 单曲线无需图例，标题即说明
                legend.set_items(items)
                legend.show()
            else:
                legend.set_items([])
                legend.hide()
            if any_series:
                plot.enableAutoRange(x=False, y=True)
            plot.setAutoVisible(y=True)
            self._apply_emphasis(title)      # 刷新后恢复 独显/悬停 态
        plots_all = list(self._plots.values())
        for p in plots_all:                  # 锁 Y：交互帧不再逐曲线重算值域
            p.getPlotItem().getViewBox().enableAutoRange(x=False, y=False)
        # 横轴铺满所选时间窗（数据从部署时刻起才有——空缺段留白诚实呈现）
        plots = list(self._plots.values())
        if plots:
            now = time.time()
            plots[0].getPlotItem().getViewBox().setXRange(
                now - self._hours * 3600, now, padding=0)

    # ------------------------------------------------------------------ 曲线强调
    def _set_emphasis(self, title: str, key, hover: bool):
        """悬停图例行 → 高亮该曲线，其余淡化。"""
        if hover:
            self._hover[title] = key
        self._apply_emphasis(title)

    def _toggle_solo(self, title: str, key: str):
        """点击图例行 → 独显该曲线；再点 → 恢复全部。"""
        self._solo[title] = None if self._solo.get(title) == key else key
        self._apply_emphasis(title)

    def _apply_emphasis(self, title: str):
        """独显：其余曲线隐藏（Y 轴自动收窄到该曲线真实区间，波动清晰展开）；
        悬停：其余淡化但保留。"""
        curves = getattr(self, "_curves", {}).get(title) or {}
        if not curves:
            return
        solo = self._solo.get(title)
        hover = self._hover.get(title)
        focus = solo or hover
        plot = self._plots.get(title)
        for k, (item, color) in curves.items():
            c = QColor(color)
            if focus is None:
                c.setAlpha(255)
                width = 1.6
            elif k == focus:
                c.setAlpha(255)
                width = 2.6
            else:
                c.setAlpha(70 if solo else 120)
                width = 1.2
            item.setPen(pg.mkPen(c, width=width))
            item.setVisible(not (solo and k != solo))
        if plot is not None:
            # 瞬时重算 Y 后立即锁定（隐藏项不计入；X 保持所选时间窗）
            vb = plot.getPlotItem().getViewBox()
            vb.enableAutoRange(x=False, y=True)
            vb.updateAutoRange()
            vb.enableAutoRange(x=False, y=False)

    def _on_ctrl_zoom(self, ev: QWheelEvent):
        """所有联动图表以光标时间为中心同步缩放 X。
        X 轴已 setXLink——只需设置主图，其余自动跟随（逐图设置会复合缩放）。
        锚点换算链：控件坐标 → mapToScene → ViewBox.mapSceneToView，
        且必须在**事件来源图**上换算（此前固定用第一个图，坐标错位导致
        缩放表现为视口平移）。"""
        factor = 1.25 if ev.angleDelta().y() > 0 else 0.8   # 滚轮上=放大
        plots = list(self._plots.values())
        if not plots:
            return
        master = plots[0].getPlotItem().getViewBox()
        (x0, x1), _ = master.viewRange()
        center = (x0 + x1) / 2.0
        src = self.sender() if isinstance(self.sender(), pg.PlotWidget) else plots[0]
        try:
            scene_pos = src.mapToScene(ev.position().toPoint())
            view_pos = master.mapSceneToView(scene_pos)
            if x0 - (x1 - x0) <= view_pos.x() <= x1 + (x1 - x0):
                center = view_pos.x()          # 光标时间（离窗过远的脏值弃用）
        except Exception:
            pass                                        # 取不到光标时间就以窗口中心
        half = (x1 - x0) / (2.0 * factor)              # factor>1 → 窗口收窄=放大
        master.setXRange(center - half, center + half, padding=0)

    def _on_reset(self):
        now = time.time()
        x0 = now - self._hours * 3600
        plots = list(self._plots.values())
        if plots:                                   # 只设主图，联动跟随
            plots[0].getPlotItem().getViewBox().setXRange(x0, now, padding=0)
        for p in plots:                             # Y 轴各自自适应
            p.getPlotItem().getViewBox().enableAutoRange(y=True)

    def _open_chart_detail(self, title: str):
        """单击图表 → 大图详情（滚轮平移 / Ctrl+滚轮缩放 / 双击复位）。"""
        curves = getattr(self, "_curves", {}).get(title) or {}
        if not curves:
            return
        series = {}
        for k, (item, color) in curves.items():
            x, y = item.getData()
            if x is None:
                continue
            series[k] = (list(x), list(y), color, _friendly(k))
        if series:
            ChartDetailDialog(title, series, self).exec()

    def shutdown(self):
        self._reap_fetcher()
