import pytest


class FakeSignal:
    def __init__(self):
        self._f = None

    def connect(self, f):
        self._f = f

    def disconnect(self):
        self._f = None

    def emit(self, v):
        if self._f:
            self._f(v)


def make_fetcher(log):
    """构造可同步完成的 HistoryFetcher 替身（不发网络请求）。"""

    def _factory(base, token, sid, keys, t_from, t_to, max_points=500):
        log.append((sid, keys, t_to - t_from))
        return type("F", (), {
            "done": FakeSignal(), "failed": FakeSignal(),
            "start": lambda self: self.done.emit(
                {"keys": {k: [[0, 1], [1, 2]] for k in keys}}),
            "isRunning": lambda self: False,
            "wait": lambda self, ms=None: None})()

    return _factory


@pytest.fixture
def page(qapp, make_settings):
    from gpuviewer_client.ui.history_page import HistoryPage
    return HistoryPage(make_settings())


def test_range_buttons_and_fetch(monkeypatch, page):
    fetched = []
    import gpuviewer_client.ui.history_page as hp
    monkeypatch.setattr(hp, "HistoryFetcher", make_fetcher(fetched))
    page.show_history("l40", hours=1)
    assert fetched[0][0] == "l40"
    assert fetched[0][1][0] == "cpu_total"
    assert fetched[0][2] == pytest.approx(3600, rel=0.01)
    assert page.plot_count() >= 7                       # 七类图表已创建


def test_plots_created_lazily(monkeypatch, page):
    """D5 部署加固：构造零成本不建图，首次 show_history 才建满 7 类，_ensure_plots 幂等。"""
    import gpuviewer_client.ui.history_page as hp
    monkeypatch.setattr(hp, "HistoryFetcher", make_fetcher([]))
    assert page.plot_count() == 0                       # 构造后：未创建任何 PlotWidget
    page.show_history("l40", hours=1)
    assert page.plot_count() >= 7                       # 首次使用时创建
    n = page.plot_count()
    page._ensure_plots()                                # 再次调用幂等，不重复建图
    assert page.plot_count() == n


def test_cache(monkeypatch, page):
    page._cache.put(("l40", 1), {"ts": 1})
    assert page._cached(("l40", 1))["ts"] == 1
    assert page._cached(("l40", 6)) is None


def test_set_servers_tracks_gpu_count_and_title(page):
    """v2：不再有下拉——set_servers 吸收 GPU 数与显示名，历史页跟随侧栏。"""
    assert not hasattr(page, "server_box")
    page.show_history("l40", 1)
    page.set_servers([{"id": "l40", "name": "L40",
                       "snapshot": {"gpus": [{} for _ in range(8)]}}])
    assert page._gpu_n == 8
    assert page.title_label.text() == "L40 · 历史趋势"
    gpu_keys = page._keys_for_title("GPU 利用率 %")
    assert gpu_keys == ["gpu:%d.util" % i for i in range(8)]


def test_history_entry_buttons(qapp, monkeypatch, client_payload, make_settings):
    """详情页"历史趋势"按钮切到页 2，历史页"返回详情"切回页 1。"""
    import gpuviewer_client.ui.history_page as hp
    from gpuviewer_client.ui.main_window import MainWindow
    monkeypatch.setattr(hp, "HistoryFetcher", make_fetcher([]))
    s = make_settings(interval_s=60)   # 测试中不轮询
    s.save()
    w = MainWindow(s)
    w.update_snapshot(client_payload)
    w.sidebar.setCurrentRow(1)
    assert w.pages.currentIndex() == 1
    w.page_detail.history_btn.click()
    assert w.pages.currentIndex() == 2
    w.page_history.back_btn.click()
    assert w.pages.currentIndex() == 1
    w.shutdown()


def test_sidebar_switch_updates_history_servers(qapp, monkeypatch, client_payload,
                                                 make_settings):
    """update_snapshot 应把服务器元数据同步给历史页（GPU 数/网卡名）。"""
    from gpuviewer_client.ui.main_window import MainWindow
    s = make_settings(interval_s=60)
    s.save()
    w = MainWindow(s)
    w.update_snapshot(client_payload)
    assert w.page_history._gpu_n == 1                 # client_payload 含 1 块 GPU
    assert "eth0" in w.page_history._ifaces
    w.shutdown()


# ---- 修复轮 R1：fetcher 串行化 / 归属键 / 单位换算 ----

class StuckFetcher:
    """永不 emit、声称在跑的 fetcher 替身（验证收尸串行化）。"""

    def __init__(self):
        self.done = FakeSignal()
        self.failed = FakeSignal()
        self.waited = 0

    def start(self):
        pass

    def isRunning(self):
        return True

    def wait(self, ms=None):
        self.waited += 1
        return True


def test_new_fetch_reaps_inflight_fetcher(monkeypatch, page):
    """C1：发起第二个不同键请求前，必须先断信号并 wait 收掉在途 fetcher。"""
    import gpuviewer_client.ui.history_page as hp
    stuck = StuckFetcher()
    box = {"stuck": stuck}

    def factory(base, token, sid, keys, t_from, t_to, max_points=500):
        if box["stuck"] is not None:
            f, box["stuck"] = box["stuck"], None
            return f
        return make_fetcher([])(base, token, sid, keys, t_from, t_to, max_points)

    monkeypatch.setattr(hp, "HistoryFetcher", factory)
    page.show_history("l40", 1)               # 第一个卡住在途
    page.show_history("a100", 1)              # 第二个：先收尸再新建
    assert stuck.waited == 1                  # 对旧 fetcher 调用过 wait
    assert stuck.done._f is None              # 且 done/failed 信号已断开
    assert page._cache.get(("a100", 1)) is not None   # 新请求正常完成


def test_same_key_inflight_not_refetched(monkeypatch, page):
    """C1：同键在途时重进视图不重发（预取→按钮点击链不串行等待 5s）。"""
    import gpuviewer_client.ui.history_page as hp
    made = []

    def factory(base, token, sid, keys, t_from, t_to, max_points=500):
        f = StuckFetcher()
        made.append(f)
        return f

    monkeypatch.setattr(hp, "HistoryFetcher", factory)
    page.show_history("l40", 1)
    page.show_history("l40", 1)               # 同键在途 → 短路
    assert len(made) == 1
    assert made[0].waited == 0


def test_late_response_binds_own_key(monkeypatch, page):
    """C1：迟到响应按发起时闭包归属键写缓存/渲染，不污染当前视图。"""
    import gpuviewer_client.ui.history_page as hp
    made = []

    class LateFetcher:
        """不主动 emit 的 fetcher；isRunning=False 使收尸直接放行（保持连接）。"""

        def __init__(self):
            self.done = FakeSignal()
            self.failed = FakeSignal()

        def start(self):
            pass

        def isRunning(self):
            return False

        def wait(self, ms=None):
            return True

    def factory(base, token, sid, keys, t_from, t_to, max_points=500):
        f = LateFetcher()
        made.append(f)
        return f

    monkeypatch.setattr(hp, "HistoryFetcher", factory)
    rendered = []
    monkeypatch.setattr(page, "_render", lambda p: rendered.append(p))
    page.show_history("l40", 1)               # A：l40
    page.show_history("4090", 1)              # B：4090（A 未 emit、已"跑完"）
    p4090 = {"keys": {k: [[0, 4090]] for k in page._keys()}}
    pl40 = {"keys": {k: [[0, 1]] for k in page._keys()}}
    made[1].done.emit(p4090)                  # 4090 先到 → 渲染并写缓存
    made[0].done.emit(pl40)                   # l40 迟到 → 只写自己的键
    assert page._cache.get(("4090", 1))["keys"]["cpu_total"] == [[0, 4090]]
    assert page._cache.get(("l40", 1))["keys"]["cpu_total"] == [[0, 1]]
    assert rendered == [p4090]                # 迟到响应不重绘当前 4090 视图


def test_mem_chart_converts_bytes_to_gb(page):
    """M2：内存图表标题为 GB，绘制前须把 mem_used 字节值换算为 GB。
    时间戳须落在所选时间窗内（渲染后横轴固定为时间窗，窗外点被裁剪）。"""
    import time as _t
    now = _t.time()
    page._render({"keys": {
        "mem_used": [[now - 60, 2 ** 30], [now - 10, 4 * 2 ** 30]],
        "cpu_total": [[now - 60, 12], [now - 10, 34]],
    }})
    mem_items = page._plots["内存使用 GB"].getPlotItem().listDataItems()
    assert mem_items, "内存图表应有曲线"
    _, ys = mem_items[-1].getData()
    assert list(ys) == [1.0, 4.0]
    cpu_items = page._plots["CPU 利用率 %"].getPlotItem().listDataItems()
    _, ys2 = cpu_items[-1].getData()
    assert list(ys2) == [12.0, 34.0]          # 其他键不缩放


# ---- 修复轮 R2：网络图按真实网卡动态取键 / 拉取失败不再静默 ----

def test_net_keys_follow_real_ifaces(monkeypatch, page):
    """I-1：CHARTS 不再硬编码 eth0——set_servers 从最新快照收集真实网卡名，
    拉取键与网络图曲线均按网卡名生成（真实环境为 eno1np0/eno1）。"""
    fetched = []
    import gpuviewer_client.ui.history_page as hp
    monkeypatch.setattr(hp, "HistoryFetcher", make_fetcher(fetched))
    page.set_servers([
        {"id": "s1", "name": "S1",
         "snapshot": {"net": [{"name": "eno1np0"}, {"name": "eno1np0"},
                              {"name": "eno2np1"}]}},
        {"id": "s2", "name": "S2", "snapshot": {"net": [{"name": "eno1"}]}},
        {"id": "s3", "name": "S3", "snapshot": None},   # 离线机：跳过
    ])
    page.show_history("s1", 1)
    keys = fetched[0][1]
    assert "net:eno1np0.rx" in keys and "net:eno1np0.tx" in keys
    assert "net:eno2np1.rx" in keys and "net:eno1.tx" in keys
    assert "net:eth0.rx" not in keys and "net:eth0.tx" not in keys
    # 去重保序：eno1np0 只出现一次，且跨服务器顺序稳定
    assert page._keys_for_title("网络 MB/s") == [
        "net:eno1np0.rx", "net:eno1np0.tx",
        "net:eno2np1.rx", "net:eno2np1.tx",
        "net:eno1.rx", "net:eno1.tx"]
    # 网络图占位行仍按标题创建，label 不变
    assert "网络 MB/s" in page._plots


def test_net_keys_fallback_eth0_before_snapshot(page):
    """I-1：未收到任何快照前回退 eth0（默认值），收到后替换。"""
    assert page._keys()[-1] == "net:eth0.tx" and "net:eth0.rx" in page._keys()
    page.set_servers([{"id": "s1", "name": "S1", "snapshot": {"net": [{"name": "eno1np0"}]}}])
    assert "net:eno1np0.rx" in page._keys() and "net:eth0.rx" not in page._keys()


def _failing_fetcher(msg):
    def _factory(base, token, sid, keys, t_from, t_to, max_points=500):
        return type("F", (), {
            "done": FakeSignal(), "failed": FakeSignal(),
            "start": lambda self: self.failed.emit(msg),
            "isRunning": lambda self: False,
            "wait": lambda self, ms=None: None})()
    return _factory


def test_fetch_failure_shows_and_clears(monkeypatch, page):
    """M4：fetch 失败不再静默——页顶 QLabel 提示，成功渲染后清除。"""
    import gpuviewer_client.ui.history_page as hp
    monkeypatch.setattr(hp, "HistoryFetcher", _failing_fetcher("boom"))
    page.show_history("l40", 1)
    assert page._error_label.text() == "历史拉取失败：boom"
    assert not page._error_label.isHidden()          # 显示
    monkeypatch.setattr(hp, "HistoryFetcher", make_fetcher([]))
    page.show_history("l40", 1)                      # 再次拉取成功
    assert page._error_label.text() == ""
    assert page._error_label.isHidden()              # 清除


# ---- v2：全 GPU 曲线 / 友好图例 / 联动缩放 ----

def test_all_gpu_series_requested(monkeypatch, page):
    """用户反馈"GPU 只显示了一个"：每块 GPU 一条曲线，键按快照 GPU 数展开。"""
    fetched = []
    import gpuviewer_client.ui.history_page as hp
    monkeypatch.setattr(hp, "HistoryFetcher", make_fetcher(fetched))
    page.set_servers([{"id": "s", "name": "S",
                       "snapshot": {"gpus": [{} for _ in range(8)]}}])
    page.show_history("s", 1)
    keys = fetched[0][1]
    for i in range(8):
        assert "gpu:%d.util" % i in keys
        assert "gpu:%d.mem_used" % i in keys
        assert "gpu:%d.temp" % i in keys
        assert "gpu:%d.power_draw" % i in keys


def test_friendly_legend_names(page):
    """图例不再是机器键名：gpu:3.mem_used→GPU3；net:eno1.rx→eno1 接收。"""
    from gpuviewer_client.ui.history_page import _friendly
    assert _friendly("gpu:3.mem_used") == "GPU3"
    assert _friendly("gpu:0.util") == "GPU0"
    assert _friendly("net:eno1np0.rx") == "eno1np0 接收"
    assert _friendly("net:eno1np0.tx") == "eno1np0 发送"
    assert _friendly("cpu_total") == "CPU"


def test_multi_series_legend_shown_single_hidden(monkeypatch, page):
    """多曲线图显示右侧图例；单曲线图隐藏图例（标题即说明）。"""
    import gpuviewer_client.ui.history_page as hp
    monkeypatch.setattr(hp, "HistoryFetcher", make_fetcher([]))
    page.set_servers([{"id": "s", "name": "S", "snapshot": {"gpus": [{} for _ in range(3)]}}])
    page.show_history("s", 1)
    gpu_leg = page._legends["GPU 利用率 %"]
    cpu_leg = page._legends["CPU 利用率 %"]
    assert not gpu_leg.isHidden()            # 多曲线：图例可见
    assert cpu_leg.isHidden()                # 单曲线：图例隐藏（标题即说明）
    assert gpu_leg._lay.count() == 3                           # 3 块 GPU 三个图例项
    assert cpu_leg._lay.count() == 0


def test_ctrl_wheel_zooms_all_linked(page):
    """Ctrl+滚轮：全部图表以中心同步缩放 X（联动，窗口宽度一致地收窄）。"""
    page._ensure_plots()
    plot0 = page._plots["CPU 利用率 %"]
    vb0 = plot0.getPlotItem().getViewBox()
    vb0.setXRange(0, 1000, padding=0)
    vb_other = page._plots["GPU 利用率 %"].getPlotItem().getViewBox()
    vb_other.setXRange(0, 1000, padding=0)

    class FakeEv:
        def modifiers(self):
            from PySide6.QtCore import Qt
            return Qt.ControlModifier

        @property
        def angleDelta(self):
            class _Delta:
                def y(self):
                    return 120

            return lambda: _Delta()

        def position(self):
            raise RuntimeError("no scene in test")      # 走中心回退分支

    page._on_ctrl_zoom(FakeEv())
    (x0, x1), _ = vb0.viewRange()
    span = x1 - x0
    assert 780 < span < 820                              # 1000/1.25=800：滚轮上=放大
    (o0, o1), _ = vb_other.viewRange()
    assert (o1 - o0) == pytest.approx(span)              # 联动等宽


def test_double_click_resets_range(page):
    """双击复位：全部图表 X 回到当前时间范围完整窗口。"""
    import time as _t
    page._ensure_plots()
    page._hours = 1
    plot0 = page._plots["CPU 利用率 %"]
    vb0 = plot0.getPlotItem().getViewBox()
    vb0.setXRange(0, 10, padding=0)
    page._on_reset()
    (x0, x1), _ = vb0.viewRange()
    assert x1 - x0 == pytest.approx(3600, rel=0.01)
    assert x1 == pytest.approx(_t.time(), abs=5)


# ---- v3：交互图例（悬停高亮/点击独显） ----

def _render3gpu(page, monkeypatch):
    import gpuviewer_client.ui.history_page as hp
    monkeypatch.setattr(hp, "HistoryFetcher", make_fetcher([]))
    page.set_servers([{"id": "s", "name": "S",
                       "snapshot": {"gpus": [{} for _ in range(3)]}}])
    page.show_history("s", 1)


def test_legend_click_solo_and_restore(monkeypatch, page):
    """点击图例行 → 独显该曲线（其余淡化细线）；再点 → 全部恢复。"""
    _render3gpu(page, monkeypatch)
    title = "GPU 利用率 %"
    page._toggle_solo(title, "gpu:1.util")
    assert page._solo[title] == "gpu:1.util"
    curves = page._curves[title]
    w_solo = curves["gpu:1.util"][0].opts["pen"].width()
    w_other = curves["gpu:0.util"][0].opts["pen"].width()
    assert w_solo > w_other                 # 独显曲线更粗
    page._toggle_solo(title, "gpu:1.util")  # 再点恢复
    assert page._solo[title] is None
    assert curves["gpu:0.util"][0].opts["pen"].width() == curves[
        "gpu:1.util"][0].opts["pen"].width()


def test_legend_hover_emphasis(monkeypatch, page):
    """悬停图例行 → 该曲线加粗，其余淡化（alpha 降低）。"""
    _render3gpu(page, monkeypatch)
    title = "GPU 温度 ℃"
    page._set_emphasis(title, "gpu:2.temp", hover=True)
    curves = page._curves[title]
    a_hot = curves["gpu:2.temp"][0].opts["pen"].color().alpha()
    a_dim = curves["gpu:0.temp"][0].opts["pen"].color().alpha()
    assert curves["gpu:2.temp"][0].opts["pen"].width() >= 3   # 2.6→QPen 取整 3
    assert a_hot == 255 and a_dim < 255
    page._set_emphasis(title, None, hover=True)   # 移开恢复
    assert curves["gpu:0.temp"][0].opts["pen"].color().alpha() == 255


def test_solo_survives_refresh(monkeypatch, page):
    """独显状态在数据刷新（_render）后保持。"""
    _render3gpu(page, monkeypatch)
    title = "GPU 功耗 W"
    page._toggle_solo(title, "gpu:2.power_draw")
    page._render({"keys": {k: [[0, 1], [1, 2]]
                           for k in page._keys_for_title(title)}})
    assert page._solo[title] == "gpu:2.power_draw"
    assert page._curves[title]["gpu:2.power_draw"][0].opts["pen"].width() >= 3


def test_x_axis_fills_selected_window_not_data_extent(monkeypatch, page):
    """选 24h 时横轴必须铺满 24 小时——即使数据只有最后几分钟
    （守护进程今天才部署，窗口左段留白是诚实呈现，不是画错）。"""
    import time as _t

    import gpuviewer_client.ui.history_page as hp
    monkeypatch.setattr(hp, "HistoryFetcher", make_fetcher([]))
    page._hours = 24
    now = _t.time()
    page._render({"keys": {"cpu_total": [[now - 300, 1], [now, 2]]}})
    vb = page._plots["CPU 利用率 %"].getPlotItem().getViewBox()
    (x0, x1), _ = vb.viewRange()
    assert (x1 - x0) == pytest.approx(24 * 3600, rel=0.01)
    assert x1 == pytest.approx(now, abs=30)


# ---- 单击/双击冲突消解 ----

class _FakePress:
    def button(self):
        from PySide6.QtCore import Qt
        return Qt.LeftButton

    def accept(self):
        pass

    def modifiers(self):
        from PySide6.QtCore import Qt
        return Qt.NoModifier


def test_single_click_opens_detail_after_delay(qtbot, page):
    """单击：260ms 后进大图（延迟判定）。"""
    page._ensure_plots()
    plot = page._plots["CPU 利用率 %"]
    opened = []
    plot.open_detail.connect(opened.append)
    plot.mousePressEvent(_FakePress())
    assert opened == []                       # 立即不弹
    qtbot.waitUntil(lambda: len(opened) == 1, timeout=2000)
    assert opened == ["CPU 利用率 %"]


def test_double_click_resets_and_cancels_open(qtbot, page):
    """双击：取消待发的进大图，执行复位（不再弹大图）。"""
    page._ensure_plots()
    plot = page._plots["CPU 利用率 %"]
    opened = []
    plot.open_detail.connect(opened.append)
    plot.mousePressEvent(_FakePress())        # 双击的第一下
    plot.mouseDoubleClickEvent(_FakePress())  # 第二下 → 取消 + 复位
    qtbot.wait(400)                           # 超过 260ms 判定窗
    assert opened == []                       # 未弹大图


# ---- TensorBoard 化：平滑 / 序列选择器 ----

def test_ema_tensorboard_formula():
    from gpuviewer_client.ui.history_page import HistoryPage
    vs = [0.0, 10.0, 10.0, 10.0]
    out = HistoryPage._ema(vs, 0.5)
    assert out[0] == 0.0
    assert out[1] == 5.0
    assert out[2] == 7.5
    assert out[3] == 8.75


def test_smooth_slider_rerenders_with_dual_lines(qtbot, monkeypatch, page):
    """滑杆>0（经 120ms 防抖后）：原始线淡化 + 平滑主线（同图两条曲线）。"""
    import gpuviewer_client.ui.history_page as hp
    monkeypatch.setattr(hp, "HistoryFetcher", make_fetcher([]))
    page._render({"keys": {"cpu_total": [[0, 10.0], [1, 20.0], [2, 30.0]]}})
    plot = page._plots["CPU 利用率 %"]
    n0 = len(plot.getPlotItem().listDataItems())
    page.smooth_slider.setValue(60)
    qtbot.waitUntil(lambda: page._smooth == 0.6, timeout=2000)   # 防抖触发
    n1 = len(plot.getPlotItem().listDataItems())
    assert page._smooth == 0.6
    assert n1 == n0 + 1                     # 多出一条淡化原始线
    assert page.smooth_value.text() == "0.60"


def test_series_selector_filters_render(monkeypatch, page):
    """左侧 GPU 复选框：取消勾选的卡不再渲染（拉取键不变，仅过滤渲染）。"""
    import gpuviewer_client.ui.history_page as hp
    monkeypatch.setattr(hp, "HistoryFetcher", make_fetcher([]))
    page.set_servers([{"id": "s", "name": "S",
                       "snapshot": {"gpus": [{} for _ in range(4)]}}])
    keys = page._keys_for_title("GPU 利用率 %")
    assert len(keys) == 4                   # 拉取键不受选择影响
    payload = {"keys": {k: [[0, 1], [1, 2]] for k in keys}}
    page._render(payload)
    curves = page._curves["GPU 利用率 %"]
    assert len(curves) == 4
    page._toggle_gpu(1, False)              # 取消 GPU1
    page._toggle_gpu(3, False)              # 取消 GPU3
    assert "gpu:1.util" not in page._curves["GPU 利用率 %"]
    assert len(page._curves["GPU 利用率 %"]) == 2
    page._set_all_series(True)              # 全选恢复
    assert len(page._curves["GPU 利用率 %"]) == 4


# ---- v1.1.0：全图联动十字线 ----

def test_sync_crosshair_updates_all_charts(page):
    """来源图取 x 时间，其余 6 张图竖线全部同步到该时间。"""
    import time as _t
    now = _t.time()
    page._ensure_plots()
    page._render({"keys": {
        "cpu_total": [[now - 600, 10], [now, 20]],
        "gpu:0.util": [[now - 600, 50], [now, 60]],
        "gpu:0.temp": [[now - 600, 70], [now, 71]],
    }})
    page._sync_crosshair("CPU 利用率 %", now - 300)
    shown = 0
    for title, (vline, tip) in page._cross.items():
        if not vline.isVisible():
            continue
        assert abs(vline.value() - (now - 300)) < 1.0
        shown += 1
    assert shown >= 3                     # 至少含来源图与两张有数据的图


def test_sparkline_records_history(qapp):
    from gpuviewer_client.ui.widgets import Sparkline
    sp = Sparkline(capacity=8)
    for i in range(12):                   # 超容量滑出，保留最后 8 个
        sp.push(float(i * 10))
    assert list(sp._buf) == [40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0, 100.0]
    sp.push(None)                         # 未知按 0 记（失联段=落底平台）
    assert sp._buf[-1] == 0.0


def test_gpu_tile_shows_model(qapp):
    from gpuviewer_client.ui.widgets import GpuTile
    tile = GpuTile()
    tile.update_gpu({"index": 2, "utilization": 80.0, "mem_used": 1000,
                     "mem_total": 24564, "temperature": 50.0}, model="RTX 4090")
    assert tile.name_label.text() == "GPU2 · RTX 4090"


def test_history_curves_not_view_clipped(qapp):
    """回归：禁用 clipToView/autoDownsample——窄视窗 setData 后扩大视窗时，
    裁剪缓存会让曲线滞留旧窗（7d 前段空白 bug）。服务端已降采样，本地裁剪多余。"""
    import time as _t

    from gpuviewer_client.ui.history_page import HistoryPage

    class _S:
        base_url, token = "http://x", "t"

    page = HistoryPage(_S())
    page._ensure_plots()
    now = _t.time()
    pts = [[now - (600 - i) * 6.0, 50.0] for i in range(601)]   # 1h 全覆盖
    page._server_id, page._hours = "s", 1.0
    page._on_done(("s", 1.0), {"keys": {"cpu_total": pts}})
    for plot in page._plots.values():
        for item in plot.getPlotItem().listDataItems():
            assert not item.opts.get("clipToView"), "clipToView 被重新启用"
            assert not item.opts.get("autoDownsample"), "autoDownsample 被重新启用"
