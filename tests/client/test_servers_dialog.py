"""服务器管理对话框：CRUD 调用接线与总服务端删除保护。"""
import pytest
from gpuviewer_client.ui.servers_dialog import ServersDialog

ENTRIES = [
    {"id": "l40", "name": "L40", "transport": "local", "enabled": True},
    {"id": "rtx", "name": "4090", "transport": "ssh", "enabled": True,
     "host": "10.0.1.2", "port": 22, "user": "u", "auth": "password", "password": "pw"},
]


@pytest.fixture
def dlg(qapp, make_settings, monkeypatch, qtbot):
    calls = []
    state = {"entries": [dict(e) for e in ENTRIES]}

    def fake_crud(settings, method, path, json_body=None):
        calls.append((method, path, json_body))
        if method == "GET":
            return state["entries"]
        if method == "DELETE":
            state["entries"] = [e for e in state["entries"]
                                if e["id"] not in path]
        return {"ok": True}

    monkeypatch.setattr("gpuviewer_client.ui.servers_dialog.crud_call", fake_crud)
    s = make_settings(token="tok")
    s.deploy_profile = {"master_id": "l40"}
    d = ServersDialog(s, None)
    qtbot.waitUntil(lambda: len(d._entries) == 2, timeout=3000)
    d.calls = calls
    d.state = state
    yield d
    if d._call is not None and d._call.isRunning():
        d._call.wait(2000)


def test_list_renders_with_master_tag(dlg):
    assert "总服务端" in dlg.lst.item(0).text()
    assert "总服务端" not in dlg.lst.item(1).text()
    assert "本机直采" in dlg.lst.item(0).text()
    assert "u@10.0.1.2:22" in dlg.lst.item(1).text()


def test_delete_master_blocked(dlg):
    dlg.lst.setCurrentRow(0)
    assert not dlg.btn_del.isEnabled()
    dlg._delete()
    assert not any(m == "DELETE" for m, _, _ in dlg.calls)


def test_delete_non_master_calls_api(dlg, qtbot):
    dlg.lst.setCurrentRow(1)
    assert dlg.btn_del.isEnabled()
    dlg._delete()
    qtbot.waitUntil(lambda: any(m == "DELETE" for m, _, _ in dlg.calls))
    assert any(p == "/api/servers/rtx" for _, p, _ in dlg.calls)


def test_add_posts_ssh_entry(dlg, qtbot):
    dlg._open_add()
    dlg.ed_id.setText("new")
    dlg.ed_name.setText("New Box")
    dlg.ed_host.setText("10.0.1.3")
    dlg.ed_user.setText("u3")
    dlg.ed_pass.setText("p3")
    dlg._save()
    qtbot.waitUntil(lambda: any(m == "POST" for m, _, _ in dlg.calls))
    body = next(b for m, _, b in dlg.calls if m == "POST")
    assert body["transport"] == "ssh" and body["host"] == "10.0.1.3"
    assert body["password"] == "p3" and body["enabled"] is True


def test_edit_prefills_and_puts(dlg, qtbot):
    dlg.lst.setCurrentRow(1)
    dlg._open_edit()
    assert dlg.ed_id.text() == "rtx" and not dlg.ed_id.isEnabled()
    assert dlg.ed_pass.text() == "pw"          # API 回显预填
    dlg.ed_name.setText("4090x")
    dlg._save()
    qtbot.waitUntil(lambda: any(m == "PUT" for m, _, _ in dlg.calls))
    method, path, body = next(c for c in dlg.calls if c[0] == "PUT")
    assert path == "/api/servers/rtx" and body["name"] == "4090x"


def test_add_requires_ssh_fields(dlg):
    dlg._open_add()
    dlg.ed_id.setText("x")
    dlg.ed_transport.setCurrentText("ssh")     # 地址/账号/密码全空
    dlg._save()
    assert not any(m == "POST" for m, _, _ in dlg.calls)
    assert "必填" in dlg.banner.text()


def test_local_transport_disables_ssh_fields(dlg):
    dlg._open_add()
    dlg.ed_transport.setCurrentText("local")
    assert not dlg.ed_host.isEnabled() and not dlg.ed_pass.isEnabled()


def test_api_error_shows_banner(dlg, monkeypatch, qtbot):
    def boom(settings, method, path, json_body=None):
        raise RuntimeError("HTTP 401：invalid token")

    monkeypatch.setattr("gpuviewer_client.ui.servers_dialog.crud_call", boom)
    dlg.reload()
    qtbot.waitUntil(lambda: "401" in dlg.banner.text(), timeout=3000)
    assert not dlg.banner.isHidden()
