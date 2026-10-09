class FakeResp:
    def __init__(self, payload, status=200):
        self._p, self.status_code = payload, status

    def json(self):
        return self._p

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("http %d" % self.status_code)


def test_settings_roundtrip(qapp, make_settings):
    s = make_settings()
    s.base_url = "http://1.2.3.4:1"
    s.token = "tk"
    s.save()
    s2 = make_settings()                      # 同一 tmp_path → 同一 INI
    assert s2.token == "tk"


def test_poller_emits(qtbot, monkeypatch, make_settings):
    from gpuviewer_client.api_client import Poller
    payload = {"version": "1", "servers": []}
    monkeypatch.setattr("gpuviewer_client.api_client.requests.get",
                        lambda url, headers, timeout: FakeResp(payload))
    s = make_settings(interval_s=60)
    p = Poller(s)
    with qtbot.waitSignal(p.snapshot_ready, timeout=3000) as blocker:
        p.start()
    assert blocker.args[0] == payload
    p.stop()
    p.wait(2000)


def test_poller_error(qtbot, monkeypatch, make_settings):
    from gpuviewer_client.api_client import Poller

    def boom(url, headers, timeout):
        raise RuntimeError("conn refused")
    monkeypatch.setattr("gpuviewer_client.api_client.requests.get", boom)
    s = make_settings(interval_s=60)
    p = Poller(s)
    with qtbot.waitSignal(p.error, timeout=3000):
        p.start()
    p.stop()
    p.wait(2000)


def test_history_fetcher(qtbot, monkeypatch):
    from gpuviewer_client.api_client import HistoryFetcher
    payload = {"server_id": "l40", "keys": {"cpu_total": [[1, 2]]}}
    monkeypatch.setattr("gpuviewer_client.api_client.requests.get",
                        lambda url, headers, timeout, params: FakeResp(payload))
    f = HistoryFetcher("http://x", "tk", "l40", ["cpu_total"], 0, 1)
    with qtbot.waitSignal(f.done, timeout=3000) as blocker:
        f.start()
    assert blocker.args[0]["keys"]["cpu_total"] == [[1, 2]]
    f.wait(2000)
