"""控件 v2：毛玻璃卡片 + 细腻动效（macOS 雅致）。

- GlassCard：大圆角半透明表面 + 发丝边框 + 悬浮辉光 + 柔和投影（自绘）
- _Anim：数值 300ms OutCubic 缓动（进度条/环形仪表）
- Dot：在线状态呼吸微光
- Sparkline：迷你趋势线（总览卡片用，2 分钟历史一眼可读）
语义色与 API（set_value/update_gpu 等）与 v1 兼容，_pct 仍为目标值。
"""
from collections import deque

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QPointF,
    QRectF,
    Qt,
    QTimer,
    QVariantAnimation,
)
from PySide6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QGuiApplication,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from gpuviewer_client.ui.theme import COLORS, MONO_STACK, RADIUS

MONO = MONO_STACK

CARD_FILL = QColor(35, 40, 50, 150)
CARD_FILL_HOVER = QColor(48, 56, 70, 176)
CHIP_FILL = QColor(30, 35, 44, 118)
HAIRLINE = QColor(255, 255, 255, 26)
HAIRLINE_HOT = QColor(88, 166, 255, 110)
SLOT_FILL = QColor(10, 12, 16, 150)


def _level_color(pct, warn=80.0, danger=95.0):
    if pct is None:
        return QColor(COLORS["offline"])
    if pct >= danger:
        return QColor(COLORS["error"])
    if pct >= warn:
        return QColor(COLORS["warning"])
    return QColor(COLORS["normal"])


def _mono(px=13, bold=False):
    f = QFont(MONO)
    f.setPointSize(px)
    f.setBold(bold)
    return f


def _styled(w, color_key="text", px=12, mono=False, bold=False):
    w.setStyleSheet("color:%s; font-size:%dpt; font-family:%s; font-weight:%s;"
                    "background:transparent;"
                    % (COLORS[color_key], px,
                       MONO if mono else "'Segoe UI Variable Display','Segoe UI','Microsoft YaHei'",
                       "600" if bold else "400"))
    return w


def _rrect(rect: QRectF, radius: float) -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    return path


class GlassCard(QFrame):
    """毛玻璃卡片：自绘大圆角表面 + 发丝边 + 悬浮态 + 柔和投影。"""

    def __init__(self, radius: float = RADIUS, hoverable: bool = True, parent=None):
        super().__init__(parent)
        self._radius = radius
        self._hoverable = hoverable
        self._hover = False
        self._shadow = 10            # 投影扩散半径（像素）
        if hoverable:
            self.setAttribute(Qt.WA_Hover, True)

    def enterEvent(self, e):
        if self._hoverable:
            self._hover = True
            self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        if self._hoverable:
            self._hover = False
            self.update()
        super().leaveEvent(e)

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        inset = 2 + self._shadow
        big = r.adjusted(-inset, -inset + 2, inset, inset + 2)
        # 柔和投影：两层低 alpha 圆角矩形
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 30))
        p.drawPath(_rrect(big.translated(0, 3), self._radius + 8))
        p.setBrush(QColor(0, 0, 0, 44))
        p.drawPath(_rrect(big.translated(0, 2), self._radius + 5))
        # 表面
        p.setBrush(CARD_FILL_HOVER if self._hover else CARD_FILL)
        p.drawPath(_rrect(r, self._radius))
        # 发丝边（悬浮时点亮）
        p.setPen(QPen(HAIRLINE_HOT if self._hover else HAIRLINE, 1))
        p.setBrush(Qt.NoBrush)
        p.drawPath(_rrect(r, self._radius))
        super().paintEvent(ev)


class _Anim:
    """数值缓动混入：目标值立即生效（_pct），显示值 300ms OutCubic 追赶。"""

    def _anim_init(self):
        self._disp = 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(300)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._anim_tick)

    def _anim_to(self, target):
        if target is None:
            self._anim.stop()
            self._disp = None
            self.update()
            return
        self._anim.stop()
        self._anim.setStartValue(float(self._disp or 0.0))
        self._anim.setEndValue(float(target))
        self._anim.start()

    def _anim_tick(self, v):
        self._disp = float(v)
        self.update()


class Dot(QWidget):
    """状态点：在线（normal）时呼吸微光。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(12, 12)
        self._color = QColor(COLORS["offline"])
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(66)          # ~15fps 呼吸
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def _is_normal(self):
        return self._color.name().lower() == QColor(COLORS["normal"]).name()

    def _tick(self):
        self._phase = (self._phase + 0.08) % 1.0
        if self._is_normal() or self._phase < 0.08:
            self.update()

    def set_color(self, name: str):
        self._color = QColor(COLORS.get(name, COLORS["offline"]))
        self.update()

    def paintEvent(self, _):
        import math
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        center = QPointF(self.rect().center())
        if self._is_normal():
            glow = 0.5 + 0.5 * math.sin(self._phase * 2 * math.pi)
            halo = QColor(self._color)
            halo.setAlpha(40 + int(70 * glow))
            p.setPen(Qt.NoPen)
            p.setBrush(halo)
            p.drawEllipse(center, 6.5, 6.5)
        p.setBrush(self._color)
        p.setPen(Qt.NoPen)
        p.drawEllipse(center, 3.2, 3.2)


class UsageBar(QWidget, _Anim):
    """用量条：缓动填充 + 内嵌文本，圆角胶囊。"""

    def __init__(self, warn=80.0, danger=95.0, height=14, parent=None):
        super().__init__(parent)
        self._pct = 0.0
        self._label = ""
        self._warn, self._danger = warn, danger
        self._anim_init()
        self.setFixedHeight(height)

    def set_value(self, pct, label=""):
        self._pct = None if pct is None else max(0.0, min(100.0, pct))
        self._label = label
        self._anim_to(self._pct)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0, 1, 0, -1)
        p.setPen(Qt.NoPen)
        p.setBrush(SLOT_FILL)
        p.drawPath(_rrect(r, min(r.height() / 2, 5)))
        if self._disp is not None and self._disp > 0.5:
            fill = QRectF(r)
            fill.setWidth(r.width() * self._disp / 100.0)
            p.setBrush(_level_color(self._pct, self._warn, self._danger))
            p.drawPath(_rrect(fill, min(r.height() / 2, 5)))
        if self._label:
            p.setPen(QPen(QColor(COLORS["text"])))
            p.setFont(_mono(8, bold=True))
            p.drawText(self.rect(), Qt.AlignCenter, self._label)


class MiniBar(QWidget, _Anim):
    """超细进度条（5px），带缓动。"""

    def __init__(self, warn=80.0, danger=95.0, parent=None):
        super().__init__(parent)
        self._pct = 0.0
        self._warn, self._danger = warn, danger
        self._anim_init()
        self.setFixedHeight(5)

    def set_value(self, pct):
        self._pct = None if pct is None else max(0.0, min(100.0, pct))
        self._anim_to(self._pct)

    def paintEvent(self, _):
        p = QPainter(self)
        r = QRectF(self.rect())
        p.setPen(Qt.NoPen)
        p.setBrush(SLOT_FILL)
        p.drawRoundedRect(r, 2, 2)
        if self._disp is not None and self._disp > 0.5:
            fill = QRectF(r)
            fill.setWidth(r.width() * self._disp / 100.0)
            p.setBrush(_level_color(self._pct, self._warn, self._danger))
            p.drawRoundedRect(fill, 2, 2)


class CoreBar(QWidget):
    """每核利用率细竖条（无动画，80 核数量级成本敏感）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pct = 0.0
        self.setFixedSize(6, 26)

    def set_value(self, pct):
        self._pct = None if pct is None else max(0.0, min(100.0, pct))
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        r = QRectF(self.rect()).adjusted(0, 0, -1, -1)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 20))
        p.drawRoundedRect(r, 2, 2)
        if self._pct:
            fill = QRectF(r)
            fill.setHeight(r.height() * self._pct / 100.0)
            fill.moveBottom(r.bottom())
            p.setBrush(_level_color(self._pct, 85.0, 95.0))
            p.drawRoundedRect(fill, 2, 2)


class GaugeRing(QWidget, _Anim):
    """环形仪表：强制正方形，缓动弧线。"""

    def __init__(self, diameter=72, parent=None):
        super().__init__(parent)
        self._pct = 0.0
        self._d = diameter
        self._anim_init()
        self.setFixedSize(diameter, diameter)

    def set_value(self, pct):
        self._pct = None if pct is None else max(0.0, min(100.0, pct))
        self._anim_to(self._pct)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        m = self._d * 0.09
        rect = QRectF(m, m, self.width() - 2 * m, self.height() - 2 * m)
        pen = QPen(QColor(255, 255, 255, 30), max(4, int(self._d / 12)))
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.drawArc(rect, 0, 360 * 16)
        if self._disp is not None and self._disp > 0.5:
            pen.setColor(_level_color(self._pct))
            p.setPen(pen)
            p.drawArc(rect, 90 * 16, -int(self._disp * 3.6) * 16)
        text = "N/A" if self._pct is None else "%d" % round(self._pct)
        p.setPen(QPen(QColor(COLORS["text"])))
        p.setFont(_mono(max(9, int(self._d / 5)), bold=True))
        p.drawText(self.rect(), Qt.AlignCenter, text)


def label_text_clipped(lbl: QLabel) -> bool:
    """标签文字是否超出可视宽度（被裁切或手动省略）。"""
    t = lbl.text()
    return bool(t) and lbl.fontMetrics().horizontalAdvance(
        t) > lbl.contentsRect().width()


class HoverPreview(QWidget):
    """跟手悬浮预览窗：快速出现、跟随光标、文本可选中复制。

    - Qt.ToolTip 窗口标志：置顶且不抢主窗焦点（WA_ShowWithoutActivating）
    - 16ms 定时器轮询光标位置实现约 60fps 跟手（绕开逐控件 mouseTracking 差异），
      move() 是纯窗口平移，无布局开销
    - 光标进入预览窗自身即冻结并保持显示——拖选文本的前提；
      选中场景下点击/拖动不触发隐藏
    - 离开源控件与预览窗超过 250ms 宽限期才隐藏（防途经空隙误收）
    """
    MAX_W = 560
    _inst: "HoverPreview | None" = None

    def __init__(self):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint)
        # 注意：不能用 Qt.ToolTip——该标志的窗口对鼠标输入透明（事件穿透
        # 到下层控件），选中/复制永远无法实现；Tool + 不抢焦点才是正解。
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self._src: QObject | None = None
        self._outside_since: int | None = None
        self._label = QLabel(self)
        self._label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        self._label.setTextFormat(Qt.TextFormat.PlainText)
        self._label.setWordWrap(True)
        self._label.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.addWidget(self._label)
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        self._anim = QVariantAnimation(self)
        self._anim.valueChanged.connect(lambda v: self.setWindowOpacity(v))

    @classmethod
    def instance(cls) -> "HoverPreview":
        if cls._inst is None:
            cls._inst = HoverPreview()
        return cls._inst

    def label(self) -> QLabel:
        return self._label

    # ---- 供过滤器调用 ----
    def show_for(self, text: str, gpos, source):
        self._src = source
        self._outside_since = None
        self._label.setText(text)
        self.setMaximumWidth(self.MAX_W)
        self.adjustSize()
        self._place(QCursor.pos() if gpos is None else gpos)
        if not self.isVisible():
            self.setWindowOpacity(0.0)
            self.show()
            self._anim.stop()
            self._anim.setStartValue(0.0)
            self._anim.setEndValue(1.0)
            self._anim.setDuration(90)
            self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            self._anim.start()
        self._timer.start()

    def track(self, cursor):
        """光标移动 → 预览窗跟随（光标在预览窗自身上时冻结）。"""
        if not self.isVisible():
            return
        if self.rect().contains(self.mapFromGlobal(cursor)):
            self._outside_since = None
            return
        self._place(cursor)

    def _place(self, gpos):
        p = gpos + QPointF(16, 20).toPoint()
        scr = QGuiApplication.screenAt(gpos) or QGuiApplication.primaryScreen()
        geo = scr.availableGeometry()
        if p.x() + self.width() > geo.right() + 1:
            p.setX(gpos.x() - self.width() - 16)
        if p.y() + self.height() > geo.bottom() + 1:
            p.setY(gpos.y() - self.height() - 20)
        self.move(max(geo.left(), p.x()), max(geo.top(), p.y()))

    def _tick(self):
        import time
        cur = QCursor.pos()
        if self.rect().contains(self.mapFromGlobal(cur)):
            self._outside_since = None          # 在预览窗上（选中/阅读）
            return
        src = self._src
        if isinstance(src, QWidget) and src.isVisible():
            tl = src.mapToGlobal(src.rect().topLeft())
            near = QRectF(tl.x() - 4, tl.y() - 4,
                          src.width() + 8, src.height() + 8)
            if near.contains(QPointF(cur)):
                self._outside_since = None      # 仍在源控件附近：跟随
                self._place(cur)
                return
        if self._outside_since is None:
            self._outside_since = time.monotonic()
        elif time.monotonic() - self._outside_since > 0.25:
            self.hide()

    def hide(self):
        self._timer.stop()
        self._anim.stop()
        super().hide()

    def mousePressEvent(self, _):
        self._label.setFocus()          # 点到边距区也把焦点交给可选中标签

    def keyPressEvent(self, e):
        """Ctrl+C / Ctrl+A：选中复制（标签有焦点时直达此处或标签自身）。"""
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if e.key() == Qt.Key.Key_C and self._label.hasSelectedText():
                QApplication.clipboard().setText(self._label.selectedText())
                return
            if e.key() == Qt.Key.Key_A:
                self._label.setSelection(0, len(self._label.text()))
                return
        super().keyPressEvent(e)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(28, 33, 40, 244))
        p.drawRoundedRect(r, 8, 8)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(240, 246, 252, 42), 1))
        p.drawRoundedRect(r, 8, 8)


def tooltip_text_for(obj, gpos):
    """解析任意控件在光标处的悬浮文本：自带 tooltip → 截断标签全文 →
    表格单元格（viewport 事件由视图解析 ToolTipRole，过滤器须代查模型，
    否则消费事件会切断视图自身的 tooltip 逻辑）。"""
    text = obj.toolTip()
    if text:
        return text
    if isinstance(obj, QLabel) and label_text_clipped(obj):
        return obj.text()
    view = None
    if isinstance(obj, QAbstractItemView):
        view = obj
    elif isinstance(getattr(obj, "parent", lambda: None)(), QAbstractItemView):
        view = obj.parent()                      # viewport → 视图
    if view is not None:
        pos = view.viewport().mapFromGlobal(gpos)
        idx = view.indexAt(pos)
        if idx.isValid():
            v = idx.data(Qt.ItemDataRole.ToolTipRole)
            if v is None:
                v = idx.data(Qt.ItemDataRole.DisplayRole)
            if v:
                return str(v)
    return None


class ElideTipFilter(QObject):
    """全局事件过滤器：把 ToolTip 事件路由到跟手预览窗 HoverPreview。

    安装在 QApplication 上（全局一次）。截断且无 tooltip 的 QLabel 以
    全文兜底；表格单元格代查模型 ToolTipRole；滚轮/预览窗外按下即收起。
    """

    def eventFilter(self, obj, e):
        t = e.type()
        if t == QEvent.ToolTip:
            try:
                text = tooltip_text_for(obj, e.globalPos())
                if text:
                    HoverPreview.instance().show_for(text, e.globalPos(), obj)
                    return True
            except RuntimeError:      # C++ 对象已销毁（窗口拆除中）
                pass
        elif t == QEvent.Wheel and not self._in_preview(obj):
            HoverPreview.instance().hide()
        elif t == QEvent.MouseButtonPress and not self._in_preview(obj):
            HoverPreview.instance().hide()
        return super().eventFilter(obj, e)

    @staticmethod
    def _in_preview(obj) -> bool:
        pv = HoverPreview._inst
        while obj is not None:
            if obj is pv:
                return True
            obj = obj.parent()
        return False


class GpuTile(GlassCard):
    """单卡瓷砖（详情页）。"""

    def __init__(self, parent=None):
        super().__init__(radius=12, hoverable=True)
        self.setFixedHeight(104)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(2)
        head = QHBoxLayout()
        head.setSpacing(4)
        self.name_label = _styled(QLabel("GPU?"), "sub", 10)
        self.temp_label = _styled(QLabel("--"), "sub", 10, mono=True)
        head.addWidget(self.name_label)
        head.addStretch(1)
        head.addWidget(self.temp_label)
        lay.addLayout(head)
        self.util_label = _styled(QLabel("--%"), "text", 17, mono=True, bold=True)
        self.util_label.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.util_label)
        self.mem_bar = UsageBar(height=12)
        lay.addWidget(self.mem_bar)
        foot = QHBoxLayout()
        self.mem_label = _styled(QLabel(""), "sub", 10, mono=True)
        self.pwr_label = _styled(QLabel(""), "sub", 10, mono=True)
        foot.addWidget(self.mem_label)
        foot.addStretch(1)
        foot.addWidget(self.pwr_label)
        lay.addLayout(foot)

    def update_gpu(self, g: dict, model: str = ""):
        self.name_label.setText("GPU%d%s" % (
            g.get("index", 0), (" · " + model) if model else ""))
        temp = g.get("temperature")
        self.temp_label.setText("%s℃" % ("--" if temp is None else "%.0f" % temp))
        self.temp_label.setStyleSheet(
            "color:%s; font-size:10pt; font-family:%s;background:transparent" % (
                COLORS["error"] if (temp or 0) >= 85 else
                (COLORS["warning"] if (temp or 0) >= 75 else COLORS["sub"]), MONO))
        util = g.get("utilization")
        self.util_label.setText("%s%%" % ("--" if util is None else "%.0f" % util))
        self.util_label.setStyleSheet(
            "color:%s; font-size:17pt; font-family:%s; font-weight:600;"
            "background:transparent" % (
                _level_color(util, 85.0, 95.0).name(), MONO))
        used, total = g.get("mem_used"), g.get("mem_total")
        if total:
            pct = (used or 0) * 100.0 / total
            self.mem_bar.set_value(pct, "%.0f%%" % pct)
            self.mem_label.setText("%.1f/%.1fG" % ((used or 0) / 1024.0,
                                                   total / 1024.0))
        else:
            self.mem_bar.set_value(None, "N/A")
            self.mem_label.setText("--")
        pw, pl = g.get("power_draw"), g.get("power_limit")
        fan = g.get("fan_speed")
        bits = []
        if pw is not None:
            bits.append("%.0fW" % pw)
        if fan is not None:
            bits.append("%.0f%%" % fan)
        self.pwr_label.setText(" ".join(bits) + ("" if pl is None else " /%.0fW" % pl))
        # 悬浮预览：瓷砖空间不够时的完整信息
        tip = ["GPU%d%s" % (g.get("index", 0), (" · " + model) if model else "")]
        if g.get("name"):
            tip.append(g["name"])
        tip.append("利用率 %s   温度 %s" % (
            "--" if util is None else "%.0f%%" % util,
            "--" if temp is None else "%.0f℃" % temp))
        if total:
            tip.append("显存 %.1f / %.1f GB（%.0f%%）" % ((used or 0) / 1024.0,
                                                        total / 1024.0, pct))
        if pw is not None:
            tip.append("功耗 %.0fW%s" % (pw, " / %.0fW" % pl if pl is not None else ""))
        self.setToolTip("\n".join(tip))


class GpuChip(QWidget):
    """单卡迷你块（总览页）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(64)
        self._hover = False
        self.setAttribute(Qt.WA_Hover, True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(1)
        head = QHBoxLayout()
        head.setSpacing(2)
        self.name_label = _styled(QLabel("GPU?"), "sub", 9)
        self.temp_label = _styled(QLabel(""), "sub", 9, mono=True)
        head.addWidget(self.name_label)
        head.addStretch(1)
        head.addWidget(self.temp_label)
        lay.addLayout(head)
        self.util_label = _styled(QLabel("--"), "text", 13, mono=True, bold=True)
        lay.addWidget(self.util_label)
        self.mem_bar = MiniBar()
        lay.addWidget(self.mem_bar)
        self.mem_label = _styled(QLabel(""), "sub", 9, mono=True)
        lay.addWidget(self.mem_label)

    def event(self, e):
        if e.type() == e.Type.HoverEnter:
            self._hover = True
            self.update()
        elif e.type() == e.Type.HoverLeave:
            self._hover = False
            self.update()
        return super().event(e)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(Qt.NoPen)
        p.setBrush(CARD_FILL_HOVER if self._hover else CHIP_FILL)
        p.drawPath(_rrect(r, 10))
        p.setPen(QPen(HAIRLINE_HOT if self._hover else HAIRLINE, 1))
        p.setBrush(Qt.NoBrush)
        p.drawPath(_rrect(r, 10))

    def update_gpu(self, g: dict):
        self.name_label.setText("GPU%d" % g.get("index", 0))
        temp = g.get("temperature")
        self.temp_label.setText("" if temp is None else "%.0f°" % temp)
        self.temp_label.setStyleSheet(
            "color:%s; font-size:9pt; font-family:%s;background:transparent" % (
                COLORS["error"] if (temp or 0) >= 85 else
                (COLORS["warning"] if (temp or 0) >= 75 else COLORS["sub"]), MONO))
        util = g.get("utilization")
        self.util_label.setText("%s%%" % ("--" if util is None else "%.0f" % util))
        self.util_label.setStyleSheet(
            "color:%s; font-size:13pt; font-family:%s; font-weight:600;"
            "background:transparent" % (
                _level_color(util, 85.0, 95.0).name(), MONO))
        used, total = g.get("mem_used"), g.get("mem_total")
        self.mem_bar.set_value(((used or 0) * 100.0 / total) if total else None)
        mem_txt = ("%.1f/%.1fG" % ((used or 0) / 1024.0, (total or 0) / 1024.0)
                   if total else "--")
        self.mem_label.setText(mem_txt)
        # 悬浮预览：小方格空间不够时的完整信息
        self.setToolTip("\n".join([
            "GPU%d%s" % (g.get("index", 0),
                         (" · " + g["name"].replace("NVIDIA ", "").replace(
                             "GeForce ", "")) if g.get("name") else ""),
            "利用率 %s%%   温度 %s" % (
                "--" if util is None else "%.0f" % util,
                "--" if temp is None else "%.0f℃" % temp),
            "显存 %s" % mem_txt]))


def section_title(text: str) -> QLabel:
    lab = _styled(QLabel(text.upper()), "sub", 9, bold=True)
    lab.setStyleSheet("color:%s; font-size:9pt; font-weight:700; letter-spacing:2px;"
                      "background:transparent" % COLORS["sub"])
    return lab


class Sparkline(QWidget):
    """迷你趋势线：定长历史 + 渐变填充 + 末端呼吸点（总览卡片用）。

    数据为 0..100 百分比序列；容量外自动滑出。绘制成本恒定
    （点数=容量，无分配），满足 5s 节拍刷新。
    """

    def __init__(self, capacity: int = 120, color: str = "#58a6ff",
                 parent=None):
        super().__init__(parent)
        self._buf: deque[float] = deque(maxlen=capacity)
        self._color = color
        self.setMinimumHeight(22)
        self.setMouseTracking(False)

    def push(self, value: float | None):
        self._buf.append(0.0 if value is None else max(0.0, min(100.0, value)))
        self.update()

    def paintEvent(self, _):
        if len(self._buf) < 2:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width() - 4, self.height()     # 右留 4px：末端圆点不被裁
        n = len(self._buf)
        step = w / float(max(n - 1, 1))
        mid = h * 0.55
        amp = h * 0.42
        pts = [QPointF(i * step, mid - (v / 100.0) * amp)
               for i, v in enumerate(self._buf)]
        # 渐变填充
        fill = QPainterPath()
        fill.moveTo(pts[0])
        for pt in pts[1:]:
            fill.lineTo(pt)
        fill.lineTo(pts[-1].x(), h)
        fill.lineTo(pts[0].x(), h)
        fill.closeSubpath()
        grad = QLinearGradient(0, 0, 0, h)
        c0 = QColor(self._color)
        c0.setAlpha(70)
        c1 = QColor(self._color)
        c1.setAlpha(0)
        grad.setColorAt(0.0, c0)
        grad.setColorAt(1.0, c1)
        p.setPen(Qt.PenStyle.NoPen)
        p.fillPath(fill, grad)
        # 主线
        pen = QPen(QColor(self._color), 1.4)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawPolyline([pt.toPoint() for pt in pts])
        # 末端呼吸点
        last = pts[-1]
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(self._color))
        p.drawEllipse(last, 2.2, 2.2)
