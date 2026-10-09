"""初始化向导：录入校验、导航流、部署完成落盘与档案写入。"""
from gpuviewer_client.deploy.tasks import DeployResult
from gpuviewer_client.ui.wizard import SetupWizard


class _FakeSignal:
    def __init__(self):
        self._slots = []

    def connect(self, f):
        self._slots.append(f)

    def emit(self, *a):
        for f in list(self._slots):
            f(*a)


class FakeDeployThread:
    last = None

    def __init__(self, master, others, parent=None):
        self.master, self.others = master, others
        for name in ("step", "log", "done", "failed", "finished"):
            setattr(self, name, _FakeSignal())
        self._running = False
        FakeDeployThread.last = self

    def start(self):
        self._running = True

    def isRunning(self):
        return self._running

    def cancel(self):
        pass


def _fill(w, name, host, user="u", pw="p", port=22):
    w.name_edit.setText(name)
    w.host_edit.setText(host)
    w.user_edit.setText(user)
    w.pass_edit.setText(pw)
    w.port_spin.setValue(port)


def test_add_requires_credentials(qapp, make_settings):
    w = SetupWizard(make_settings())
    _fill(w, "L40", "")                       # 地址空 → 拒绝
    w._add_server()
    assert w._specs == []
    assert not w.btn_next.isEnabled()


def test_navigate_to_master_page(qapp, make_settings):
    w = SetupWizard(make_settings())
    _fill(w, "L40", "10.0.1.1")
    w._add_server()
    _fill(w, "4090", "10.0.1.2")
    w._add_server()
    assert w.btn_next.isEnabled()
    w._next()
    assert w.stack.currentIndex() == 1
    assert w.master_list.count() == 2
    assert w.master_list.currentRow() == 0    # 默认选第一台


def test_deploy_flow_applies_settings(qapp, make_settings, monkeypatch):
    s = make_settings()
    w = SetupWizard(s)
    _fill(w, "L40", "10.0.1.1", pw="secret")
    w._add_server()
    _fill(w, "4090", "10.0.1.2")
    w._add_server()
    w._next()                                  # → 总服务端页
    monkeypatch.setattr("gpuviewer_client.ui.wizard.DeployThread", FakeDeployThread)
    w.master_list.setCurrentRow(1)             # 选 4090 当总服务端
    w._next()                                  # 开始部署
    assert FakeDeployThread.last is not None
    assert FakeDeployThread.last.master.host == "10.0.1.2"
    assert [o.host for o in FakeDeployThread.last.others] == ["10.0.1.1"]
    assert w.stack.currentIndex() == 2

    w._on_step("连接与预检")
    w._on_deploy_done(DeployResult(base_url="http://10.0.1.2:7421", token="tok123",
                                   master_id="4090", master_name="4090"))
    assert w.stack.currentIndex() == 3
    # 必须走真实按钮：完成页曾把进度页的禁用态带过来，按钮点不动（假线程
    # isRunning 恒 True，靠方法直调测不出来）
    assert w.btn_next.isEnabled()
    w.btn_next.click()
    assert s.token == "tok123"
    assert s.base_url == "http://10.0.1.2:7421"
    prof = s.deploy_profile
    assert prof["host"] == "10.0.1.2" and prof["password"] == "p"   # 4090 的凭据
    assert prof["master_id"] == "4090"


def test_deploy_failure_keeps_progress_page(qapp, make_settings, monkeypatch):
    w = SetupWizard(make_settings())
    _fill(w, "L40", "10.0.1.1")
    w._add_server()
    w._next()
    monkeypatch.setattr("gpuviewer_client.ui.wizard.DeployThread", FakeDeployThread)
    w._next()
    w._on_deploy_failed("SSH 执行失败")
    assert w.stack.currentIndex() == 2          # 停在进度页，可返回重试
    assert "SSH 执行失败" in w.log_view.toPlainText()
    FakeDeployThread.last._running = False      # 模拟真实线程已结束
    w._sync_nav()
    w.btn_back.click()
    assert w.stack.currentIndex() == 1
