"""无边框窗标题栏 v2：Windows 式三键（— ▢ ✕）+ 应用图标 + 标题。

拖拽/缩放仍由主窗 WM_NCHITTEST 交给系统；按钮自身区域交还客户区可点。
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from gpuviewer_client.ui.theme import COLORS

HTLEFT, HTRIGHT, HTTOP, HTTOPLEFT, HTTOPRIGHT = (10, 11, 12, 13, 14)
HTBOTTOM, HTBOTTOMLEFT, HTBOTTOMRIGHT = (15, 16, 17)
BORDER = 6


def hit_test(x: int, y: int, w: int, h: int, caption_h: int) -> int:
    """(窗口内局部坐标) → Windows 非客户区命中码（拖拽/八向缩放）。"""
    if x < BORDER and y < BORDER:
        return HTTOPLEFT
    if x > w - BORDER and y < BORDER:
        return HTTOPRIGHT
    if x < BORDER and y > h - BORDER:
        return HTBOTTOMLEFT
    if x > w - BORDER and y > h - BORDER:
        return HTBOTTOMRIGHT
    if x < BORDER:
        return HTLEFT
    if x > w - BORDER:
        return HTRIGHT
    if y < BORDER:
        return HTTOP
    if y > h - BORDER:
        return HTBOTTOM
    if y < caption_h:
        return 2   # HTCAPTION
    return 1       # HTCLIENT


def make_app_icon(size: int = 64) -> QIcon:
    """应用图标：蓝紫渐变圆角方 + 白色监控脉冲线（无字母，窗口/任务栏/托盘共用）。"""
    from PySide6.QtCore import QPointF
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    grad = QLinearGradient(0, 0, size, size)
    grad.setColorAt(0.0, QColor("#58a6ff"))
    grad.setColorAt(1.0, QColor("#8957e5"))
    p.setBrush(grad)
    p.setPen(Qt.PenStyle.NoPen)
    m = size * 0.08
    p.drawRoundedRect(int(m), int(m), int(size - 2 * m), int(size - 2 * m),
                      int(size * 0.24), int(size * 0.24))
    # 监控脉冲折线（心跳/利用率曲线意涵）
    pen = QPen(QColor("white"), max(2.0, size * 0.06))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    u = size * 0.20                      # 左边距
    w = size - 2 * u                     # 可用宽
    base = size * 0.66                   # 基线
    pts = [
        QPointF(u, base),
        QPointF(u + w * 0.22, base),
        QPointF(u + w * 0.30, size * 0.34),   # 上升尖峰
        QPointF(u + w * 0.40, base * 0.92),
        QPointF(u + w * 0.52, base * 0.92),
        QPointF(u + w * 0.60, size * 0.26),   # 主尖峰
        QPointF(u + w * 0.72, base),
        QPointF(u + w, base),
    ]
    path = QPainterPath()
    path.moveTo(pts[0])
    for pt in pts[1:]:
        path.lineTo(pt)
    p.drawPath(path)
    p.end()
    return QIcon(pm)


class _CaptionButton(QPushButton):
    """Windows 式窗口控制按钮：无边透明，悬浮底色（关闭键红色）。"""

    def __init__(self, glyph: str, tip: str, danger: bool = False, parent=None):
        super().__init__(glyph, parent)
        self._danger = danger
        self.setFixedSize(44, 32)
        self.setToolTip(tip)
        self.setCursor(Qt.PointingHandCursor)
        self.setFlat(True)
        hot = "#c42b1c" if danger else "rgba(255,255,255,26)"
        self.setStyleSheet(
            "QPushButton { border:none; border-radius:6px; background:transparent;"
            " color:#e8eaed; font-size:11pt; font-family:'Segoe MDL2 assets','Segoe UI'; }"
            "QPushButton:hover { background:%s; color:%s; }"
            % (hot, "white" if danger else "#e8eaed"))


class TitleBar(QWidget):
    """左：图标 + 标题；右：— ▢ ✕ 三键。"""

    close_requested = Signal()
    minimize_requested = Signal()
    maximize_requested = Signal()
    DRAG_HEIGHT = 40

    def __init__(self, title: str = "", icon: QIcon | None = None, parent=None):
        super().__init__(parent)
        self.setFixedHeight(self.DRAG_HEIGHT)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 0, 6, 0)
        lay.setSpacing(8)
        icon_label = QLabel()
        icon_label.setFixedSize(20, 20)
        if icon is not None:
            icon_label.setPixmap(icon.pixmap(20, 20))
        self.title_label = QLabel(title)
        self.title_label.setStyleSheet(
            "color:%s; font-size:11pt; font-weight:600; background:transparent;"
            "font-family:'Segoe UI Variable Display','Segoe UI','Microsoft YaHei';"
            % COLORS["text"])
        lay.addWidget(icon_label)
        lay.addWidget(self.title_label)
        lay.addStretch(1)

        btn_min = _CaptionButton("—", "最小化")
        btn_max = _CaptionButton("▢", "最大化 / 还原")
        btn_close = _CaptionButton("✕", "关闭", danger=True)
        btn_min.clicked.connect(self.minimize_requested.emit)
        btn_max.clicked.connect(self.maximize_requested.emit)
        btn_close.clicked.connect(self.close_requested.emit)
        lay.addWidget(btn_min)
        lay.addWidget(btn_max)
        lay.addWidget(btn_close)

    def set_title(self, title: str):
        self.title_label.setText(title)

    def mousePressEvent(self, e):
        # 系统级窗口拖动（Qt 原生 startSystemMove，DPI 安全；
        # 子按钮自行消费点击，事件不会到这里，天然不冲突）
        if e.button() == Qt.LeftButton and self.window() is not None:
            wh = self.window().windowHandle()
            if wh is not None:
                wh.startSystemMove()
                e.accept()
                return
        super().mousePressEvent(e)

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton:
            e.accept()
            self.maximize_requested.emit()
        else:
            super().mouseDoubleClickEvent(e)
