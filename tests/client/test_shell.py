import pytest


@pytest.fixture
def win(qapp, make_settings):
    from gpuviewer_client.ui.main_window import MainWindow
    s = make_settings(interval_s=60)   # 测试中不轮询
    s.save()
    w = MainWindow(s)
    yield w
    w.shutdown()


def test_main_window_constructs(win):
    assert win.windowTitle() == "GPUViewer"
    assert win.sidebar_server_ids() == []
    assert win.minimumWidth() == 1200 and win.minimumHeight() == 800


def test_sidebar_updates(win, client_payload):
    win.update_snapshot(client_payload)
    assert win.sidebar_server_ids() == ["l40"]
    assert win.banner_text() == ""            # 全在线无横幅


def test_overview_card_navigates_to_detail(win, client_payload):
    win.update_snapshot(client_payload)
    assert win.pages.currentIndex() == 0
    win.page_overview._cards["l40"].click()
    assert win.sidebar.currentRow() == 1
    assert win.pages.currentIndex() == 1


def test_sidebar_select_loads_detail(win, client_payload):
    win.update_snapshot(client_payload)
    win.sidebar.setCurrentRow(1)
    assert win.page_detail.host_label.text() == "L40"
    assert win.page_detail.gpu_tiles[0].util_label.text() == "87%"
    assert win.page_detail.proc_model_cpu.rowCount() == 1


def test_banner_offline(win, client_payload):
    p = client_payload
    p["servers"][0]["status"] = "offline"
    win.update_snapshot(p)
    assert "失联" in win.banner_text()


def test_gauge_and_bar(qapp):
    from gpuviewer_client.ui.widgets import GaugeRing, UsageBar
    g = GaugeRing()
    g.set_value(87.0)
    assert g._pct == 87.0
    b = UsageBar()
    b.set_value(73.5, "73.5%")
    assert b._pct == 73.5


def test_widgets_unknown_value_kept(qapp):
    """I-3：None（未知）不得与真实 0% 混淆。"""
    from gpuviewer_client.ui.widgets import GaugeRing, UsageBar
    g = GaugeRing()
    g.set_value(87.0)
    g.set_value(None)
    assert g._pct is None
    b = UsageBar()
    b.set_value(73.5)
    b.set_value(None, "?")
    assert b._pct is None


def test_current_server_reads_id_not_name(win, client_payload):
    """I-2：侧栏选中行应按 UserRole 存的 id 取回 state（name "L40" ≠ id "l40"）。"""
    win.update_snapshot(client_payload)
    assert win.sidebar.currentRow() == 0        # 启动停在"总览"
    win.sidebar.setCurrentRow(1)
    assert win._current_server(client_payload["servers"]) is client_payload["servers"][0]
    win.sidebar.setCurrentRow(0)
    assert win._current_server(client_payload["servers"]) is None


# ---- 初始化向导 / 服务器管理接线 ----

def test_sidebar_has_servers_button(win):
    from PySide6.QtWidgets import QPushButton
    texts = [b.text() for b in win.findChildren(QPushButton)]
    assert "＋ 服务器" in texts and "⚙ 设置" in texts


def test_manage_servers_unconfigured_opens_wizard(win, monkeypatch):
    import gpuviewer_client.ui.main_window as mw

    class FakeWizard:
        constructed = 0

        def __init__(self, settings, parent=None):
            FakeWizard.constructed += 1

        def exec(self):
            return False

    monkeypatch.setattr(mw, "SetupWizard", FakeWizard)
    assert not win.settings.is_configured       # win 夹具 token 为空
    win.manage_servers()
    assert FakeWizard.constructed == 1


def test_manage_servers_configured_opens_manager(win, monkeypatch):
    import gpuviewer_client.ui.main_window as mw

    class FakeManager:
        constructed = 0

        def __init__(self, settings, parent=None):
            FakeManager.constructed += 1

        def exec(self):
            return True

    monkeypatch.setattr(mw, "ServersDialog", FakeManager)
    win.settings.token = "tok"
    win.manage_servers()
    assert FakeManager.constructed == 1


def test_setup_wizard_accept_restarts_polling(win, monkeypatch):
    order = []

    class FakeWizard:
        def __init__(self, settings, parent=None):
            pass

        def exec(self):
            return True

    class _Sig:
        def connect(self, f):
            pass

    class FakePoller:
        def __init__(self, settings):
            self.snapshot_ready = _Sig()
            self.error = _Sig()

        def stop(self):
            order.append("stop")

        def wait(self, ms):
            order.append("wait")

        def isRunning(self):
            return False

        def start(self):
            order.append("start")

    monkeypatch.setattr("gpuviewer_client.ui.main_window.SetupWizard", FakeWizard)
    monkeypatch.setattr("gpuviewer_client.ui.main_window.Poller", FakePoller)
    win.start_polling()                          # 建第一个 FakePoller（记 1 次 start）
    assert win.run_setup_wizard() is True
    assert order == ["start", "stop", "wait", "start"]  # 向导保存后热重启顺序


def test_maybe_show_wizard_only_when_unconfigured(win, monkeypatch):
    calls = []
    monkeypatch.setattr(win, "run_setup_wizard", lambda: calls.append(1) or True)
    win.maybe_show_wizard()                     # token 空 → 弹
    assert len(calls) == 1
    win.settings.token = "tok"
    win.maybe_show_wizard()
    assert len(calls) == 1                      # 已配置不再弹


def _srv(base, sid, name):
    return dict(base, id=sid, name=name)


def test_sidebar_full_sync(win, client_payload):
    """侧栏与快照全量同步：消失移除、改名刷新；选中机被删回总览。

    旧行为只增不删：daemon 侧删除服务器后侧栏留幽灵行（2026-10-08 用户删
    4090 后侧栏仍显示）。
    """
    base = client_payload["servers"][0]
    win.update_snapshot({"version": "1", "servers": [_srv(base, "a", "A"),
                                                     _srv(base, "b", "B")]})
    assert win.sidebar_server_ids() == ["a", "b"]
    win.update_snapshot({"version": "1", "servers": [_srv(base, "a", "A2")]})
    assert win.sidebar_server_ids() == ["a"]            # b 消失即移除
    assert win.sidebar.item(1).text() == "A2"           # 改名刷新
    win.sidebar.setCurrentRow(1)                        # 选中 a 看详情
    assert win.pages.currentIndex() == 1
    win.update_snapshot({"version": "1", "servers": []})
    assert win.sidebar_server_ids() == []
    assert win.sidebar.currentRow() == 0                # 选中机被删 → 回总览
    assert win.pages.currentIndex() == 0
