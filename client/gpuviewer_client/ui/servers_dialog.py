"""服务器管理：对已部署 daemon 的被监控服务器做增删改（CRUD 即时生效）。

数据源永远是 daemon 的 /api/servers（含凭据回显预填）。总服务端（部署档案
中的 master_id）不可删除——客户端连接与全部远程采集都依赖它。
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from gpuviewer_client.api_client import ApiCall, crud_call
from gpuviewer_client.ui.theme import DARK_QSS


class ServersDialog(QDialog):
    def __init__(self, settings, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("服务器管理")
        self.setMinimumSize(560, 560)
        self.setStyleSheet(DARK_QSS)
        self._s = settings
        self._entries: list[dict] = []
        self._editing: dict | None = None        # None=新增, dict=编辑该条
        self._call: ApiCall | None = None
        self._profile = settings.deploy_profile or {}

        root = QVBoxLayout(self)
        title = QLabel("被监控服务器")
        title.setObjectName("title")
        root.addWidget(title)
        sub = QLabel("新增的 SSH 服务器不做任何安装——总服务端经 SSH 直接采集"
                     "（目标机需有 python3 与 base64）。修改即时生效。")
        sub.setObjectName("sub")
        sub.setWordWrap(True)
        root.addWidget(sub)

        self.banner = QLabel("")
        self.banner.setObjectName("banner")
        self.banner.setWordWrap(True)
        self.banner.hide()
        root.addWidget(self.banner)

        self.lst = QListWidget()
        self.lst.setObjectName("picker")
        self.lst.currentRowChanged.connect(self._sync_buttons)
        root.addWidget(self.lst, 1)

        row = QHBoxLayout()
        self.btn_add = QPushButton("新增…")
        self.btn_edit = QPushButton("编辑…")
        self.btn_del = QPushButton("删除")
        self.btn_refresh = QPushButton("刷新")
        for b in (self.btn_add, self.btn_edit, self.btn_del, self.btn_refresh):
            row.addWidget(b)
        row.addStretch(1)
        self.btn_close = QPushButton("关闭")
        row.addWidget(self.btn_close)
        root.addLayout(row)
        self.btn_add.clicked.connect(self._open_add)
        self.btn_edit.clicked.connect(self._open_edit)
        self.btn_del.clicked.connect(self._delete)
        self.btn_refresh.clicked.connect(self.reload)
        self.btn_close.clicked.connect(self.accept)

        self.editor = self._build_editor()
        self.editor.hide()
        root.addWidget(self.editor)
        self._sync_editor_mode()

        self.reload()

    # ---------- 数据 ----------

    def reload(self):
        self._api("list", lambda: crud_call(self._s, "GET", "/api/servers"))

    def _api(self, op: str, fn):
        self.btn_add.setEnabled(False)
        self.btn_edit.setEnabled(False)
        self.btn_del.setEnabled(False)
        self.btn_refresh.setEnabled(False)
        t = ApiCall(fn, self)
        t.done.connect(lambda payload: self._on_ok(op, payload))
        t.failed.connect(self._on_err)
        t.finished.connect(self._on_done_call)
        self._call = t
        t.start()

    def _on_done_call(self):
        self.btn_add.setEnabled(True)
        self.btn_refresh.setEnabled(True)
        self._sync_buttons()

    def _on_ok(self, op: str, payload):
        self.banner.hide()
        if op == "list":
            self._entries = payload or []
            self._render()
        else:
            self.editor.hide()
            self._editing = None
            self._sync_editor_mode()
            self.reload()

    def _on_err(self, msg: str):
        self.banner.setText("操作失败：" + msg)
        self.banner.show()

    def _render(self):
        self.lst.clear()
        for e in self._entries:
            where = (f"{e.get('user')}@{e.get('host')}:{e.get('port')}"
                     if e.get("transport") == "ssh" else "本机直采")
            tag = "　[总服务端]" if e.get("id") == self._profile.get("master_id") else ""
            state = "" if e.get("enabled", True) else "　（已停用）"
            it = QListWidgetItem(f"{e.get('name')} · {where}{tag}{state}")
            it.setData(Qt.UserRole, e)
            self.lst.addItem(it)
        self._sync_buttons()

    def _selected(self) -> dict | None:
        item = self.lst.currentItem()
        return item.data(Qt.UserRole) if item else None

    def _is_master(self, e: dict) -> bool:
        return bool(e) and e.get("id") == self._profile.get("master_id")

    def _sync_buttons(self):
        e = self._selected()
        self.btn_edit.setEnabled(e is not None)
        self.btn_del.setEnabled(e is not None and not self._is_master(e))
        if e is not None and self._is_master(e):
            self.btn_del.setToolTip("总服务端承载守护进程与历史数据，不可在此删除")
        else:
            self.btn_del.setToolTip("")

    # ---------- 编辑器 ----------

    def _build_editor(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self.ed_id = QLineEdit()
        self.ed_id.setPlaceholderText("唯一标识（字母/数字/-/_）")
        self.ed_name = QLineEdit()
        self.ed_transport = QComboBox()
        self.ed_transport.addItems(["ssh", "local"])
        self.ed_host = QLineEdit()
        self.ed_port = QSpinBox()
        self.ed_port.setRange(1, 65535)
        self.ed_port.setValue(22)
        self.ed_user = QLineEdit()
        self.ed_pass = QLineEdit()
        self.ed_pass.setEchoMode(QLineEdit.EchoMode.Password)
        self.ed_enabled = QCheckBox("启用采集")
        self.ed_enabled.setChecked(True)
        form.addRow("ID", self.ed_id)
        form.addRow("名称", self.ed_name)
        form.addRow("传输", self.ed_transport)
        form.addRow("地址", self.ed_host)
        form.addRow("端口", self.ed_port)
        form.addRow("账号", self.ed_user)
        form.addRow("密码", self.ed_pass)
        form.addRow("", self.ed_enabled)
        row = QHBoxLayout()
        self.btn_save = QPushButton("保存")
        self.btn_cancel = QPushButton("取消")
        self.btn_save.clicked.connect(self._save)
        self.btn_cancel.clicked.connect(self._close_editor)
        row.addStretch(1)
        row.addWidget(self.btn_cancel)
        row.addWidget(self.btn_save)
        form.addRow(row)
        self.ed_transport.currentTextChanged.connect(self._sync_editor_mode)
        return w

    def _sync_editor_mode(self, *_):
        ssh = self.ed_transport.currentText() == "ssh"
        for w in (self.ed_host, self.ed_port, self.ed_user, self.ed_pass):
            w.setEnabled(ssh)

    def _open_add(self):
        self._editing = None
        for w in (self.ed_id, self.ed_name, self.ed_host, self.ed_user, self.ed_pass):
            w.clear()
        self.ed_transport.setCurrentText("ssh")
        self.ed_port.setValue(22)
        self.ed_enabled.setChecked(True)
        self.ed_id.setEnabled(True)
        self.editor.show()
        self.ed_id.setFocus()

    def _open_edit(self):
        e = self._selected()
        if e is None:
            return
        self._editing = e
        self.ed_id.setText(e.get("id", ""))
        self.ed_id.setEnabled(False)              # PUT 要求 id 与路径一致，不可改
        self.ed_name.setText(e.get("name", ""))
        self.ed_transport.setCurrentText(e.get("transport", "ssh"))
        self.ed_host.setText(e.get("host") or "")
        self.ed_port.setValue(e.get("port") or 22)
        self.ed_user.setText(e.get("user") or "")
        self.ed_pass.setText(e.get("password") or "")
        self.ed_enabled.setChecked(e.get("enabled", True))
        self.editor.show()

    def _close_editor(self):
        self.editor.hide()
        self._editing = None

    def _save(self):
        body = {
            "id": self.ed_id.text().strip(),
            "name": self.ed_name.text().strip() or self.ed_id.text().strip(),
            "transport": self.ed_transport.currentText(),
            "enabled": self.ed_enabled.isChecked(),
        }
        if body["transport"] == "ssh":
            body.update({"host": self.ed_host.text().strip(),
                         "port": self.ed_port.value(),
                         "user": self.ed_user.text().strip(),
                         "auth": "password",
                         "password": self.ed_pass.text()})
            if not body["id"] or not body["host"] or not body["user"] or not body["password"]:
                self._on_err("ID / 地址 / 账号 / 密码 必填")
                return
        elif not body["id"]:
            self._on_err("ID 必填")
            return
        if self._editing is None:
            self._api("save", lambda: crud_call(self._s, "POST", "/api/servers", body))
        else:
            sid = self._editing["id"]
            self._api("save", lambda: crud_call(self._s, "PUT", f"/api/servers/{sid}", body))

    def _delete(self):
        e = self._selected()
        if e is None or self._is_master(e):
            return
        sid = e["id"]
        self._api("delete", lambda: crud_call(self._s, "DELETE", f"/api/servers/{sid}"))
