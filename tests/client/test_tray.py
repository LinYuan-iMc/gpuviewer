"""托盘行为：不弹气泡（用户要求移除），tooltip 摘要与图标保留。"""


def test_no_balloon_popup_api(qapp, make_settings):
    """MainWindow 不再暴露任何气泡路径：无 handle_alerts、无 show_message。"""
    from gpuviewer_client.ui.main_window import MainWindow, TrayController
    s = make_settings()
    w = MainWindow(s)
    assert not hasattr(w, "handle_alerts")
    assert not hasattr(TrayController, "show_message")
    w.update_snapshot({"servers": []})          # 正常路径不抛错
    w.shutdown()


def test_update_snapshot_refreshes_tooltip(qapp, client_payload, make_settings):
    """update_snapshot 应把每台一行 CPU/GPU 摘要写到托盘 tooltip。"""
    from gpuviewer_client.ui.main_window import MainWindow
    s = make_settings()
    s.save()
    w = MainWindow(s)
    w.update_snapshot(client_payload)
    assert "L40" in w.tray.icon.toolTip()
    assert "CPU 12%" in w.tray.icon.toolTip()
    w.shutdown()
