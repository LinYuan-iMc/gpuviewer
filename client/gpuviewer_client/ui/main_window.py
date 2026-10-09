"""主窗 v2：无边框毛玻璃 + macOS 红绿灯标题栏 + 侧栏导航 + 三页栈。

- FramelessWindowHint + WA_TranslucentBackground，系统 Acrylic 从背后透出
- 标题栏/边缘经 WM_NCHITTEST 交给系统：原生拖拽、双击最大化、八向缩放
- 图标化最小化到托盘；关闭=退出
"""
import ctypes
import sys

from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QPushButton,
    QStackedWidget,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from gpuviewer_client.api_client import Poller
from gpuviewer_client.ui import glass
from gpuviewer_client.ui.detail_page import DetailPage
from gpuviewer_client.ui.history_page import HistoryPage
from gpuviewer_client.ui.overview_page import OverviewPage
from gpuviewer_client.ui.servers_dialog import ServersDialog
from gpuviewer_client.ui.settings_dialog import SettingsDialog
from gpuviewer_client.ui.theme import DARK_QSS, SURFACE
from gpuviewer_client.ui.title_bar import TitleBar, make_app_icon
from gpuviewer_client.ui.widgets import ElideTipFilter
from gpuviewer_client.ui.wizard import SetupWizard

_TRAY_KEEPALIVE: list = []


class TrayController:
    """系统托盘：图标 + 右键菜单 + tooltip 摘要。

    注意：icon 不作为 MainWindow 子对象，且控制器进程级存活——
    PySide6/Windows 下随窗口销毁连带析构 QSystemTrayIcon 会破坏堆
    （进程随后在任意线程 access violation）。真实应用主窗与进程同寿命，
    该注册表只是把生命周期显式化，无额外泄漏。
    """

    def __init__(self, window: "MainWindow"):
        self.window = window
        self.icon = QSystemTrayIcon(self._make_icon())
        _TRAY_KEEPALIVE.append(self)
        self.menu = QMenu()
        show_action = QAction("显示主窗口", self.menu)
        show_action.triggered.connect(window.showNormal)
        quit_action = QAction("退出", self.menu)
        quit_action.triggered.connect(window.close)
        self.menu.addAction(show_action)
        self.menu.addAction(quit_action)
        self.icon.setContextMenu(self.menu)
        self.icon.activated.connect(self._on_activated)
        self.icon.show()

    def _on_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.window.showNormal()

    @staticmethod
    def _make_icon() -> QIcon:
        return make_app_icon()

    def tooltip_lines(self, summaries) -> list[str]:
        lines = ["%s  CPU %s%%  GPU %s%%" % s for s in summaries] or ["GPUViewer"]
        self.icon.setToolTip("\n".join(lines))
        return lines


class MainWindow(QMainWindow):
    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        self.setWindowTitle("GPUViewer")
        self.resize(1280, 840)
        self.setMinimumSize(1200, 800)
        # 截断标签的悬浮全文预览（全局一次，覆盖所有页面）
        self._elide_tip = ElideTipFilter(self)
        QApplication.instance().installEventFilter(self._elide_tip)

        # ---- 无边框 + 毛玻璃 ----
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        central = QWidget()
        central.setStyleSheet("background:%s;" % SURFACE["window"])
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        root = QVBoxLayout()
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self._app_icon = make_app_icon()
        self.setWindowIcon(self._app_icon)
        self.title_bar = TitleBar("GPUViewer", icon=self._app_icon)
        self.title_bar.close_requested.connect(self.close)
        self.title_bar.minimize_requested.connect(self._minimize)
        self.title_bar.maximize_requested.connect(self._toggle_max)
        root.addWidget(self.title_bar)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        # 侧边栏
        side = QWidget()
        side.setFixedWidth(200)
        side.setStyleSheet("background:rgba(14,17,23,96);")
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(10, 6, 10, 12)
        self.sidebar = QListWidget()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.addItem("总览")
        self._server_rows = {}                # id -> row index
        servers_btn = QPushButton("＋ 服务器")
        servers_btn.clicked.connect(self.manage_servers)
        settings_btn = QPushButton("⚙ 设置")
        settings_btn.clicked.connect(self.show_settings)
        self.daemon_label = QLabel("守护进程 · 连接中…")
        self.daemon_label.setWordWrap(True)
        self.daemon_label.setStyleSheet(
            "color:#9aa4b2; font-size:9pt; background:transparent;")
        side_layout.addWidget(self.sidebar, 1)
        side_layout.addWidget(self.daemon_label)
        side_layout.addWidget(servers_btn)
        side_layout.addWidget(settings_btn)

        # 页面栈：0 总览 / 1 详情 / 2 历史趋势
        self.pages = QStackedWidget()
        self.page_overview = OverviewPage()
        self.page_overview.server_clicked.connect(self.open_server)
        self.page_detail = DetailPage()
        self.page_detail.history_requested.connect(self.show_history_page)
        self.page_history = HistoryPage(settings)
        self.page_history.back_requested.connect(self.show_detail_page)
        self.pages.addWidget(self.page_overview)
        self.pages.addWidget(self.page_detail)
        self.pages.addWidget(self.page_history)

        right = QVBoxLayout()
        right.setContentsMargins(6, 6, 6, 6)
        self.banner = QLabel("", objectName="banner")
        self.banner.hide()
        right.addWidget(self.banner)
        right.addWidget(self.pages, 1)
        wrapper = QWidget()
        wrapper.setStyleSheet("background:transparent;")
        wrapper.setLayout(right)

        body.addWidget(side)
        body.addWidget(wrapper, 1)
        root.addLayout(body, 1)
        layout.addLayout(root)
        self.setCentralWidget(central)
        self.setStyleSheet(DARK_QSS)
        self.sidebar.currentRowChanged.connect(self._nav)

        self._poller = None
        self._last_poll_ts = 0.0
        self._last_servers = []
        self._hist_sid = None                   # 已预取历史的服务器
        self.sidebar.setCurrentRow(0)           # 启动默认选中"总览"
        self.tray = TrayController(self)
        self._install_shortcuts()
        self._restore_geometry()

    # ---- 无边框窗：系统级拖拽/缩放 ----
    def nativeEvent(self, eventType, message):
        """只处理窗口边缘的八向缩放命中。

        标题栏拖拽由 TitleBar.startSystemMove 负责（DPI 安全），
        按钮区域完全不经过本命中测试——彻底规避坐标换算偏差。"""
        if eventType == "windows_generic_MSG":
            try:
                msg = ctypes.wintypes.MSG.from_address(int(message))
            except Exception:
                return super().nativeEvent(eventType, message)
            if msg.message == 0x84:             # WM_NCHITTEST
                dpr = self.devicePixelRatioF() or 1.0
                raw_x = ctypes.c_short(msg.lParam & 0xFFFF).value
                raw_y = ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value
                gpos = self.mapFromGlobal(QPoint(round(raw_x / dpr),
                                                 round(raw_y / dpr)))
                border = 5
                w, h = self.width(), self.height()
                x, y = gpos.x(), gpos.y()
                if x < 0 or y < 0 or x > w or y > h:
                    return super().nativeEvent(eventType, message)
                if x < border and y < border:
                    return True, 13             # HTTOPLEFT
                if x > w - border and y < border:
                    return True, 14             # HTTOPRIGHT
                if x < border and y > h - border:
                    return True, 16             # HTBOTTOMLEFT
                if x > w - border and y > h - border:
                    return True, 17             # HTBOTTOMRIGHT
                if x < border:
                    return True, 10             # HTLEFT
                if x > w - border:
                    return True, 11             # HTRIGHT
                if y < border:
                    return True, 12             # HTTOP
                if y > h - border:
                    return True, 15             # HTBOTTOM
        return super().nativeEvent(eventType, message)
        return super().nativeEvent(eventType, message)

    def showEvent(self, e):
        super().showEvent(e)
        if sys.platform == "win32" and not getattr(self, "_glass_on", False):
            hwnd = int(self.winId())
            self._glass_on = glass.enable_acrylic(hwnd)
            glass.force_round_corners(hwnd)

    def _minimize(self):
        self.showMinimized()

    def _toggle_max(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def _install_shortcuts(self):
        """键盘导航：1/2/3 切页，Esc 逐级返回。"""
        from PySide6.QtGui import QKeySequence, QShortcut
        for key, idx in (("1", 0), ("2", 1), ("3", 2)):
            sc = QShortcut(QKeySequence(key), self)
            sc.activated.connect(lambda i=idx: self._goto_page(i))
        esc = QShortcut(QKeySequence("Esc"), self)
        esc.activated.connect(self._esc_back)

    def _goto_page(self, idx: int):
        if idx == 0:
            self.sidebar.setCurrentRow(0)
            self.pages.setCurrentIndex(0)
        elif idx in (1, 2) and self._selected_server_id():
            if idx == 1:
                self.pages.setCurrentIndex(1)
            else:
                self.show_history_page()

    def _esc_back(self):
        cur = self.pages.currentIndex()
        if cur == 2:
            self.show_detail_page()
        elif cur == 1:
            self.sidebar.setCurrentRow(0)
            self.pages.setCurrentIndex(0)

    def _restore_geometry(self):
        geo_hex = self.settings.qs.value("window_geometry", "")
        state = self.settings.qs.value("window_maximized", False)
        if geo_hex:
            try:
                self.restoreGeometry(bytes.fromhex(geo_hex))
            except Exception:
                pass
        if state:
            self.showMaximized()

    def _save_geometry(self):
        self.settings.qs.setValue("window_geometry", self.saveGeometry().toHex().data().decode())
        self.settings.qs.setValue("window_maximized", self.isMaximized())
        self.settings.qs.sync()

    def closeEvent(self, e):
        self._save_geometry()
        super().closeEvent(e)

    # ---- 供测试/子类使用的钩子 ----
    def start_polling(self):
        if self._poller is None:
            self._poller = Poller(self.settings)
            self._poller.snapshot_ready.connect(self.update_snapshot)
            self._poller.error.connect(self._on_poll_error)
        if not self._poller.isRunning():
            self._poller.start()

    def _on_poll_error(self, msg):
        self.banner.setText("守护进程不可达：%s" % msg)
        self.banner.show()

    def update_snapshot(self, payload: dict):
        import time as _t
        self._last_poll_ts = _t.time()
        servers = payload.get("servers", [])
        self._last_servers = servers
        self._refresh_sidebar(servers)
        offline = [s for s in servers if s["status"] == "offline"]
        if offline:
            parts = []
            now = _t.time()
            for s in offline:
                age = now - (s.get("last_success_ts") or now)
                parts.append("%s（最后数据 %d 分钟前）" % (
                    s["name"], int(age // 60)) if age >= 60 else s["name"])
            self.banner.setText("⚠ %s 已失联（显示最后成功数据）"
                                % "、".join(parts))
            self.banner.show()
        else:
            self.banner.hide()
        # 阈值状态由页面颜色呈现（红/黄），不再弹托盘气泡打扰（用户要求移除）
        import time as _t
        self.daemon_label.setText(
            "守护进程 v%s · 在线 · 刷新 %ds 前 · %d 台服务器"
            % (payload.get("version", "?"), int(_t.time() - self._last_poll_ts),
               len(servers)))
        self.tray.tooltip_lines(self._tray_summary(servers))
        # 子页面更新钩子
        self.page_overview.update_snapshot(servers)
        self.page_history.set_servers(servers)
        self.page_detail.update_state(self._current_server(servers))

    @staticmethod
    def _tray_summary(servers) -> list[tuple]:
        rows = []
        for s in servers:
            snap = s.get("snapshot") or {}
            cpu = (snap.get("cpu") or {}).get("utilization_total") or 0
            gpus = snap.get("gpus") or [{}]
            gpu0 = gpus[0].get("utilization") or 0
            rows.append((s["name"], int(cpu), int(gpu0)))
        return rows

    def _current_server(self, servers):
        item = self.sidebar.currentItem()
        sid = item.data(Qt.UserRole) if item else None
        for s in servers:
            if s["id"] == sid:
                return s
        return None

    def _refresh_sidebar(self, servers):
        """与快照全量同步：新增插入、消失移除、改名刷新；选中机被删回总览。

        旧行为只增不删——daemon 侧删除服务器后侧栏留幽灵行（2026-10-08
        用户删 4090 后侧栏仍显示）。行序保持首次出现顺序，daemon 不提供重排。
        """
        want = {s["id"]: s["name"] for s in servers}
        for sid in list(self._server_rows):
            if sid not in want:
                row = self._server_rows.pop(sid)
                self.sidebar.takeItem(row)
                self._server_rows = {k: (r - 1 if r > row else r)
                                     for k, r in self._server_rows.items()}
        for sid, name in want.items():
            if sid not in self._server_rows:
                item = QListWidgetItem(name)
                item.setData(Qt.UserRole, sid)   # 选中行按 id（而非显示名）回查 state
                self.sidebar.addItem(item)
                self._server_rows[sid] = self.sidebar.count() - 1
            else:
                self.sidebar.item(self._server_rows[sid]).setText(name)
        if self.sidebar.currentRow() > 0 and self._selected_server_id() not in want:
            self.sidebar.setCurrentRow(0)        # 触发 _nav 回总览，清掉详情页残影

    def sidebar_server_ids(self):
        return list(self._server_rows.keys())

    def banner_text(self):
        return self.banner.text()

    def _selected_server_id(self):
        item = self.sidebar.currentItem()
        return item.data(Qt.UserRole) if item else None

    def _nav(self, row):
        if row <= 0:                             # -1=移除行时的空选，与 0 同归总览
            self.pages.setCurrentIndex(0)
            return
        sid = self._selected_server_id()
        # 切机走 show_server：重置三张表的选择/滚动位置后整体装载
        self.page_detail.show_server(self._current_server(self._last_servers))
        # 侧栏当前服务器变化时预取该机历史（窗口可见才发请求，测试构造不打网络）
        if sid and sid != self._hist_sid and self.isVisible():
            self._hist_sid = sid
            self.page_history.show_history(sid, self.page_history.hours)
        self.pages.setCurrentIndex(1)

    def show_history_page(self):
        """从详情页进入历史页：装载当前服务器后切到页 2。"""
        sid = self._selected_server_id() or self._hist_sid
        if sid:
            self.page_history.show_history(sid, self.page_history.hours)
        self.pages.setCurrentIndex(2)

    def show_detail_page(self):
        self.pages.setCurrentIndex(1)

    def open_server(self, server_id: str):
        """总览卡片点击→侧栏选中对应行并切到详情页（装载该机 state）。"""
        for sid, row in self._server_rows.items():
            if sid == server_id:
                self.sidebar.setCurrentRow(row)   # 触发 _nav 装载详情
        self.pages.setCurrentIndex(1)

    def show_settings(self):
        dlg = SettingsDialog(self.settings, self)
        if dlg.exec():                          # 保存（accepted）后热重启轮询
            self._restart_polling()

    def _restart_polling(self):
        if self._poller:
            self._poller.stop()
            self._poller.wait(4000)             # ≥ Poller HTTP timeout 3s，防丢线程引用
            self._poller = None
        self.start_polling()

    def manage_servers(self):
        """侧栏「＋ 服务器」：未初始化进向导，已初始化进服务器管理。"""
        if not self.settings.is_configured:
            self.run_setup_wizard()
        else:
            ServersDialog(self.settings, self).exec()

    def run_setup_wizard(self) -> bool:
        wiz = SetupWizard(self.settings, self)
        if wiz.exec():
            self._restart_polling()             # 向导写入了新 base_url/token
            return True
        return False

    def maybe_show_wizard(self):
        """首启（未配置 token）自动弹初始化向导；由 __main__ 在 start_polling 前调用。"""
        if not self.settings.is_configured:
            self.run_setup_wizard()

    def shutdown(self):
        if self._poller:
            self._poller.stop()
            self._poller.wait(4000)
        self.page_history.shutdown()
        self.tray.icon.hide()

    def changeEvent(self, event):
        super().changeEvent(event)
        if (event.type() == QEvent.Type.WindowStateChange and self.isMinimized()
                and self.tray.icon.isSystemTrayAvailable()):
            self.hide()                        # 最小化隐藏到托盘
