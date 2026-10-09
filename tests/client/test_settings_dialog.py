def test_dialog_save(qapp, make_settings):
    from gpuviewer_client.ui.settings_dialog import SettingsDialog
    s = make_settings()
    dlg = SettingsDialog(s)
    dlg.url_edit.setText("http://9.9.9.9:1")
    dlg.interval_spin.setValue(10.0)
    dlg.accept()                                   # 触发保存
    s2 = make_settings()
    assert s2.base_url == "http://9.9.9.9:1"
    assert s2.interval_s == 10.0


def test_interval_allows_one_second(qapp, make_settings):
    """1s 间隔合法：下限 0.5s，不得被范围钳到 2s（匹配 daemon 1s 采集）。"""
    from gpuviewer_client.ui.settings_dialog import SettingsDialog
    s = make_settings(interval_s=1.0)
    dlg = SettingsDialog(s)
    assert dlg.interval_spin.value() == 1.0        # 打开即显示真实值
    dlg.interval_spin.setValue(0.5)
    dlg._save()
    assert s.interval_s == 0.5


def test_dialog_cancel_keeps_old(qapp, make_settings):
    from gpuviewer_client.settings import AppSettings
    from gpuviewer_client.ui.settings_dialog import SettingsDialog
    s = make_settings(**AppSettings.DEFAULTS)
    s.save()
    dlg = SettingsDialog(s)
    dlg.url_edit.setText("http://9.9.9.9:1")
    dlg.reject()
    s2 = make_settings()
    assert s2.base_url == AppSettings.DEFAULTS["base_url"]


def test_main_window_settings_button(qapp, monkeypatch, client_payload, make_settings):
    from gpuviewer_client.ui.main_window import MainWindow
    s = make_settings()
    s.save()
    w = MainWindow(s)
    opened = []
    monkeypatch.setattr(
        "gpuviewer_client.ui.main_window.SettingsDialog",
        lambda settings, parent=None: (opened.append(1), type("D", (), {
            "exec": lambda self: 0})())[1])
    w.show_settings()
    assert opened == [1]
    w.shutdown()


def test_settings_restart_waits_full_http_timeout(qapp, monkeypatch, make_settings):
    """I1：热重启等待须 ≥ Poller 的 HTTP timeout 3s（与 shutdown 一致取 4s）。"""
    import gpuviewer_client.ui.main_window as mw
    s = make_settings()
    s.save()
    calls = []

    class _Sig:
        def connect(self, f):
            pass

    class FakePoller:
        snapshot_ready = _Sig()
        error = _Sig()

        def __init__(self, settings):
            pass

        def start(self):
            calls.append("start")

        def stop(self):
            calls.append("stop")

        def wait(self, ms):
            calls.append(("wait", ms))
            return True

        def isRunning(self):
            return False

    class FakeDialog:
        def __init__(self, settings, parent=None):
            pass

        def exec(self):
            return 1                        # 模拟"保存"

    monkeypatch.setattr(mw, "Poller", FakePoller)
    monkeypatch.setattr(mw, "SettingsDialog", FakeDialog)
    w = mw.MainWindow(s)
    w.start_polling()
    w.show_settings()
    assert ("wait", 4000) in calls
    assert calls.index("stop") < calls.index(("wait", 4000)) < calls.index("start", 1)
    w.shutdown()
