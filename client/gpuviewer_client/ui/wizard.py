"""初始化向导：录入服务器 → 选总服务端 → 客户端自动部署 daemon → 完成。

首启（token 为空）自动弹出；也可经侧栏「＋ 服务器」在未配置时再次进入。
四页 QStackedWidget：服务器列表 / 选总服务端 / 部署进度 / 完成摘要。
非总服务端不做任何部署——daemon 经 SSH 远程采集，探针纯标准库。
"""
import logging

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from gpuviewer_client.deploy.tasks import REMOTE_DIR, DeployResult, ServerSpec
from gpuviewer_client.deploy.threads import DeployThread, PrecheckThread
from gpuviewer_client.ui.theme import DARK_QSS

STEPS = ["连接与预检", "上传代码", "写入配置", "安装依赖并启动服务", "健康检查"]


class SetupWizard(QDialog):
    def __init__(self, settings, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("初始化 GPUViewer")
        self.setMinimumSize(620, 560)
        self.setStyleSheet(DARK_QSS)
        self._s = settings
        self._specs: list[ServerSpec] = []
        self._test_thread: PrecheckThread | None = None
        self._deploy_thread: DeployThread | None = None
        self._result: DeployResult | None = None
        self._deploy_master: ServerSpec | None = None
        self._token_visible = False

        root = QVBoxLayout(self)
        title = QLabel("初始化 GPUViewer")
        title.setObjectName("title")
        root.addWidget(title)
        sub = QLabel("录入 GPU 服务器（SSH 地址 / 账号 / 密码），选一台作为总服务端，"
                     "客户端将自动在其上安装监控守护进程。")
        sub.setObjectName("sub")
        sub.setWordWrap(True)
        root.addWidget(sub)

        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)
        self.stack.addWidget(self._page_servers())
        self.stack.addWidget(self._page_master())
        self.stack.addWidget(self._page_progress())
        self.stack.addWidget(self._page_done())

        nav = QHBoxLayout()
        self.btn_back = QPushButton("上一步")
        self.btn_next = QPushButton("下一步")
        self.btn_back.clicked.connect(self._back)
        self.btn_next.clicked.connect(self._next)
        nav.addWidget(self.btn_back)
        nav.addStretch(1)
        nav.addWidget(self.btn_next)
        root.addLayout(nav)
        self._goto(0)

    # ---------- 页面构建 ----------

    def _page_servers(self) -> QWidget:
        w = QWidget()
        col = QVBoxLayout(w)
        form = QFormLayout()
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("显示名（留空则用地址）")
        self.host_edit = QLineEdit()
        self.host_edit.setPlaceholderText("服务器 IP 或主机名")   # 不放具体示例，防被照抄
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(22)
        self.user_edit = QLineEdit()
        self.user_edit.setPlaceholderText("SSH 登录用户")
        self.pass_edit = QLineEdit()
        self.pass_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.pass_edit.setPlaceholderText("SSH 密码")
        form.addRow("显示名", self.name_edit)
        form.addRow("地址", self.host_edit)
        form.addRow("端口", self.port_spin)
        form.addRow("账号", self.user_edit)
        form.addRow("密码", self.pass_edit)
        col.addLayout(form)

        row = QHBoxLayout()
        self.btn_test = QPushButton("测试连接")
        self.btn_add = QPushButton("添加到列表")
        self.btn_test.clicked.connect(self._on_test)
        self.btn_add.clicked.connect(self._add_server)
        row.addWidget(self.btn_test)
        row.addWidget(self.btn_add)
        row.addStretch(1)
        self.test_label = QLabel("")
        self.test_label.setObjectName("sub")
        row.addWidget(self.test_label)
        col.addLayout(row)

        self.srv_list = QListWidget()
        col.addWidget(self.srv_list, 1)
        remove_row = QHBoxLayout()
        self.btn_remove = QPushButton("移除选中")
        self.btn_remove.clicked.connect(self._remove_server)
        remove_row.addWidget(self.btn_remove)
        remove_row.addStretch(1)
        col.addLayout(remove_row)
        return w

    def _page_master(self) -> QWidget:
        w = QWidget()
        col = QVBoxLayout(w)
        hint = QLabel("选择一台作为总服务端（运行守护进程、存储全部历史数据）。"
                      "其余服务器不做任何安装，由总服务端经 SSH 直接采集。")
        hint.setObjectName("sub")
        hint.setWordWrap(True)
        col.addWidget(hint)
        self.master_list = QListWidget()
        self.master_list.setObjectName("picker")
        col.addWidget(self.master_list, 1)
        return w

    def _page_progress(self) -> QWidget:
        w = QWidget()
        col = QVBoxLayout(w)
        self.step_labels: dict[str, QLabel] = {}
        for name in STEPS:
            lab = QLabel("·  " + name)
            lab.setObjectName("sub")
            self.step_labels[name] = lab
            col.addWidget(lab)
        col.addSpacing(8)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(400)
        col.addWidget(self.log_view, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        self.btn_cancel = QPushButton("取消部署")
        self.btn_cancel.clicked.connect(self._cancel_deploy)
        row.addWidget(self.btn_cancel)
        col.addLayout(row)
        return w

    def _page_done(self) -> QWidget:
        w = QWidget()
        col = QVBoxLayout(w)
        ok = QLabel("初始化完成，已自动绑定")
        ok.setObjectName("title")
        col.addWidget(ok)
        form = QFormLayout()
        self.done_url = QLabel("")
        self.done_url.setTextInteractionFlags(Qt.TextSelectableByMouse)
        form.addRow("服务地址", self.done_url)
        token_row = QHBoxLayout()
        self.done_token = QLabel("")
        self.done_token.setTextInteractionFlags(Qt.TextSelectableByMouse)
        token_row.addWidget(self.done_token)
        btn_show = QPushButton("显示")
        btn_show.clicked.connect(self._toggle_token)
        btn_copy = QPushButton("复制")
        btn_copy.clicked.connect(self._copy_token)
        token_row.addWidget(btn_show)
        token_row.addWidget(btn_copy)
        token_row.addStretch(1)
        form.addRow("Token", token_row)
        self.done_mode = QLabel("")
        form.addRow("部署模式", self.done_mode)
        col.addLayout(form)
        self.done_notes = QLabel("")
        self.done_notes.setObjectName("sub")
        self.done_notes.setWordWrap(True)
        col.addWidget(self.done_notes)
        col.addStretch(1)
        return w

    # ---------- 页 1：服务器录入 ----------

    def _on_test(self):
        spec = self._form_spec()
        if spec is None:
            return
        self.btn_test.setEnabled(False)
        self._set_test_label("连接中…", "")
        self._test_thread = PrecheckThread(spec, self)
        self._test_thread.ok.connect(lambda m: self._set_test_label(m, "ok"))
        self._test_thread.failed.connect(lambda m: self._set_test_label(m, "err"))
        self._test_thread.finished.connect(lambda: self.btn_test.setEnabled(True))
        self._test_thread.start()

    def _set_test_label(self, msg: str, state: str):
        self.test_label.setText(msg)
        # ok/err objectName 走 DARK_QSS；回退 sub 需重抛样式
        self.test_label.setObjectName(state if state else "sub")
        self.test_label.style().unpolish(self.test_label)
        self.test_label.style().polish(self.test_label)
        # 报错原文落盘：截图/口述都不可靠，日志才是排障的第一现场
        if state == "err":
            logging.getLogger("gpuviewer.wizard").error("测试连接失败：%s", msg)
        elif state == "ok":
            logging.getLogger("gpuviewer.wizard").info("测试连接：%s", msg)

    def _form_spec(self) -> ServerSpec | None:
        host = self.host_edit.text().strip()
        user = self.user_edit.text().strip()
        password = self.pass_edit.text()
        if not host or not user or not password:
            self._set_test_label("地址 / 账号 / 密码必填", "err")
            return None
        return ServerSpec(name=self.name_edit.text().strip() or host, host=host,
                          port=self.port_spin.value(), user=user, password=password)

    def _add_server(self):
        spec = self._form_spec()
        if spec is None:
            return
        self._specs.append(spec)
        item = QListWidgetItem(f"{spec.name} · {spec.user}@{spec.host}:{spec.port}")
        item.setData(Qt.UserRole, spec)
        self.srv_list.addItem(item)
        self.name_edit.clear()
        self.host_edit.clear()
        self.user_edit.clear()
        self.pass_edit.clear()
        self._set_test_label("", "")
        self._sync_nav()

    def _remove_server(self):
        row = self.srv_list.currentRow()
        if row < 0:
            return
        self.srv_list.takeItem(row)
        self._specs.pop(row)
        self._sync_nav()

    # ---------- 导航 ----------

    def _goto(self, idx: int):
        if idx == 1:
            self._rebuild_master()
        self.stack.setCurrentIndex(idx)
        self._sync_nav()

    def _back(self):
        self._goto(self.stack.currentIndex() - 1)

    def _next(self):
        idx = self.stack.currentIndex()
        if idx == 0:
            self._goto(1)
        elif idx == 1:
            self._start_deploy()
        elif idx == 3:
            self._apply()
            self.accept()

    def _sync_nav(self):
        idx = self.stack.currentIndex()
        running = self._deploy_thread is not None and self._deploy_thread.isRunning()
        self.btn_back.setVisible(idx in (1,) and not running)
        if idx == 0:
            self.btn_next.setText("下一步")
            self.btn_next.setEnabled(bool(self._specs))
        elif idx == 1:
            self.btn_next.setText("开始部署")
            self.btn_next.setEnabled(self.master_list.count() > 0)
        elif idx == 2:
            self.btn_next.setText("完成")
            self.btn_next.setEnabled(not running and self._result is not None)
        else:
            self.btn_next.setText("完成")
            self.btn_next.setEnabled(True)     # 完成页恒可点——进度页禁用态不得带过来
        self.btn_cancel.setVisible(idx == 2 and running)

    def _rebuild_master(self):
        self.master_list.clear()
        for spec in self._specs:
            self.master_list.addItem(
                QListWidgetItem(f"{spec.name} · {spec.user}@{spec.host}:{spec.port}"))
        if self.master_list.count():
            self.master_list.setCurrentRow(0)

    # ---------- 部署 ----------

    def _start_deploy(self):
        row = self.master_list.currentRow()
        if row < 0 or row >= len(self._specs):
            return
        master = self._specs[row]
        self._deploy_master = master
        others = [s for i, s in enumerate(self._specs) if i != row]
        for name in STEPS:
            self.step_labels[name].setText("·  " + name)
            self.step_labels[name].setObjectName("sub")
        self.log_view.clear()
        self._result = None
        self._deploy_thread = DeployThread(master, others, self)
        self._deploy_thread.step.connect(self._on_step)
        self._deploy_thread.log.connect(self._on_log)
        self._deploy_thread.done.connect(self._on_deploy_done)
        self._deploy_thread.failed.connect(self._on_deploy_failed)
        self._deploy_thread.finished.connect(self._sync_nav)   # 线程结束恢复导航
        self._deploy_thread.start()
        self._goto(2)

    def _on_step(self, name: str):
        for i, s in enumerate(STEPS):
            lab = self.step_labels[s]
            if s == name:
                lab.setText("●  " + s)
                lab.setObjectName("title")
            elif i < STEPS.index(name):
                lab.setText("✓  " + s)
            lab.style().unpolish(lab)
            lab.style().polish(lab)

    def _on_log(self, line: str):
        self.log_view.appendPlainText(line)

    def _on_deploy_done(self, result: DeployResult):
        self._result = result
        for s in STEPS:
            self.step_labels[s].setText("✓  " + s)
        self.done_url.setText(result.base_url)
        self._token_visible = False
        self._render_token()
        self.done_mode.setText("复用已有部署（保留 token 与历史）" if result.reused
                               else "全新部署")
        self.done_notes.setText("\n".join(result.notes))
        self._goto(3)

    def _on_deploy_failed(self, msg: str):
        self._on_log("✗ " + msg)
        logging.getLogger("gpuviewer.wizard").error("部署失败：%s", msg)
        self._sync_nav()

    def _cancel_deploy(self):
        if self._deploy_thread is not None:
            self._deploy_thread.cancel()
        self._on_log("已请求取消（等待当前步骤结束后生效，安装步骤不可中断）…")

    # ---------- 完成 ----------

    def _render_token(self):
        r = self._result
        if r is None:
            return
        self.done_token.setText(
            r.token if self._token_visible else "••••••••（已自动保存到设置）")

    def _toggle_token(self):
        self._token_visible = not self._token_visible
        self._render_token()

    def _copy_token(self):
        if self._result is not None:
            QGuiApplication.clipboard().setText(self._result.token)

    def _apply(self):
        r = self._result
        if r is None:
            return
        self._s.base_url = r.base_url
        self._s.token = r.token
        self._s.save()
        master = self._deploy_master
        if master is not None:
            self._s.deploy_profile = {
                "master_id": r.master_id, "master_name": r.master_name,
                "host": master.host, "port": master.port,
                "user": master.user, "password": master.password,
                "remote_dir": REMOTE_DIR,
            }

    # ---------- 关闭保护 ----------

    def reject(self):                                   # Esc / 关闭按钮
        if self._deploy_thread is not None and self._deploy_thread.isRunning():
            self._on_log("部署进行中：请先等待完成或点「取消部署」")
            return
        if self._test_thread is not None and self._test_thread.isRunning():
            self._test_thread.wait(4000)
        super().reject()
