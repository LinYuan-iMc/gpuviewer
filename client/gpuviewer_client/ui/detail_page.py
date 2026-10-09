"""详情页：nvitop 式高密度单机全景。

分区（自上而下）：
  1. 头行：状态点·名称·系统·内核·开机 | 负载 | [历史趋势]
  2. GPU 瓷砖阵（4 列 × N 行）：大利用率 + 显存条 + 温度/功耗/风扇
  3. 占卡进程表：全量列出（高度=行数×22，最多 14 行后滚动）
  4. 系统带（三面板横排）：CPU(环+负载+每核阵) | 内存(+Swap) | 磁盘+网络(逐行条)
  5. TOP 进程双表并排（CPU | 内存），高度=10 行全显
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from gpuviewer_client.models import ProcessTableModel
from gpuviewer_client.ui.overview_page import fmt_bytes, fmt_uptime
from gpuviewer_client.ui.widgets import (
    CoreBar,
    Dot,
    GaugeRing,
    GlassCard,
    GpuTile,
    MiniBar,
    UsageBar,
    _styled,
    section_title,
)

PROC_HEADERS = ["PID", "用户", "GPU", "显存", "显存%", "SM%", "带宽%", "CPU%",
                "内存", "运行", "命令"]
TOP_HEADERS = ["PID", "用户", "CPU%", "MEM%", "命令"]


def _table(model, stretch_col: int, cap_rows: int = 14) -> QTableView:
    t = QTableView()
    t.setModel(model)
    t.verticalHeader().hide()
    t.setShowGrid(False)
    t.setSelectionBehavior(QTableView.SelectRows)
    t.setWordWrap(False)
    # 命令列不用 Stretch：窄窗口下它会被挤到 0 宽且横向滚动条永不出现
    # （Stretch 时列宽总和恒等于视口）。改 Interactive 固定初始宽 +
    # 像素级横向滚动；超宽文本省略号，悬浮已支持显示全文。
    t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
    t.horizontalHeader().setSectionResizeMode(stretch_col, QHeaderView.Interactive)
    t.setColumnWidth(stretch_col, 340)
    t.setHorizontalScrollMode(QTableView.ScrollMode.ScrollPerPixel)
    t.horizontalHeader().setFixedHeight(24)
    t.verticalHeader().setDefaultSectionSize(22)
    t.setMinimumHeight(30 + 22 * cap_rows)
    t.setStyleSheet(
        "QTableView::item { padding: 1px 6px; }"
        "QTableView { font-size: 10pt; font-family: Consolas, monospace; }")
    return t


class _Panel(GlassCard):
    def __init__(self, title: str):
        super().__init__(radius=12, hoverable=False)
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(10, 8, 10, 8)
        self.lay.setSpacing(3)
        self.lay.addWidget(section_title(title))


class DetailPage(QScrollArea):
    history_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        # ---- 头行 ----
        self.dot = Dot()
        self.host_label = _styled(QLabel(""), "text", 15, bold=True)
        self.host_sub = _styled(QLabel(""), "sub", 10)
        self.load_label = _styled(QLabel(""), "text", 11, mono=True)
        self.history_btn = QPushButton("历史趋势")
        self.history_btn.clicked.connect(self.history_requested.emit)
        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(self.dot)
        head.addWidget(self.host_label)
        head.addWidget(self.host_sub)
        head.addStretch(1)
        head.addWidget(_styled(QLabel("负载 1/5/15"), "sub", 10))
        head.addWidget(self.load_label)
        head.addWidget(self.history_btn)

        # ---- GPU 瓷砖阵 ----
        self.gpu_grid_host = QWidget()
        self.gpu_grid = QGridLayout(self.gpu_grid_host)
        self.gpu_grid.setContentsMargins(0, 0, 0, 0)
        self.gpu_grid.setSpacing(6)
        self.gpu_tiles: list[GpuTile] = []
        self.gpu_model = ProcessTableModel(PROC_HEADERS)
        self.gpu_table = _table(self.gpu_model, stretch_col=10, cap_rows=14)

        # ---- 系统带 ----
        sys_band = QHBoxLayout()
        sys_band.setSpacing(6)
        # CPU 面板：大数值 + 负载行 + 右侧环 + 每核阵
        cpu_panel = _Panel("CPU")
        cpu_head = QHBoxLayout()
        cpu_head.setSpacing(10)
        head_left = QVBoxLayout()
        head_left.setSpacing(0)
        self.cpu_big = _styled(QLabel("--"), "text", 20, mono=True, bold=True)
        self.load_detail = _styled(QLabel(""), "sub", 10, mono=True)
        head_left.addWidget(self.cpu_big)
        head_left.addWidget(self.load_detail)
        cpu_head.addLayout(head_left, 1)
        self.cpu_ring = GaugeRing(diameter=58)
        cpu_head.addWidget(self.cpu_ring, 0, Qt.AlignTop)
        cpu_panel.lay.addLayout(cpu_head)
        self.cores_label = _styled(QLabel(""), "sub", 9)
        cpu_panel.lay.addWidget(self.cores_label)
        self.core_host = QWidget()
        self.core_lay = QGridLayout(self.core_host)
        self.core_lay.setContentsMargins(0, 0, 0, 0)
        self.core_lay.setSpacing(2)
        cpu_panel.lay.addWidget(self.core_host)
        cpu_panel.lay.addStretch(1)
        self.core_bars: list[CoreBar] = []
        # 内存面板：大百分比 + 主条 + 明细行
        mem_panel = _Panel("内存")
        self.mem_pct = _styled(QLabel("--"), "text", 20, mono=True, bold=True)
        self.mem_bar = UsageBar(height=14)
        self.mem_label = _styled(QLabel(""), "sub", 10, mono=True)
        mem_panel.lay.addWidget(self.mem_pct)
        mem_panel.lay.addWidget(self.mem_bar)
        mem_panel.lay.addWidget(self.mem_label)
        self.swap_label = _styled(QLabel(""), "sub", 10, mono=True)
        self.swap_bar = UsageBar(height=10)
        self.cached_label = _styled(QLabel(""), "sub", 10, mono=True)
        mem_panel.lay.addWidget(self.swap_label)
        mem_panel.lay.addWidget(self.swap_bar)
        mem_panel.lay.addWidget(self.cached_label)
        mem_panel.lay.addStretch(1)
        # 磁盘+网络面板（逐行紧凑，不再一行占一卡）
        dn_panel = _Panel("磁盘 / 网络")
        self.disk_rows: dict[str, tuple[QLabel, MiniBar, QLabel]] = {}
        self.net_rows: dict[str, QLabel] = {}
        self.dn_lay = QVBoxLayout()
        self.dn_lay.setSpacing(2)
        dn_panel.lay.addLayout(self.dn_lay)
        dn_panel.lay.addStretch(1)
        sys_band.addWidget(cpu_panel, 34)
        sys_band.addWidget(mem_panel, 22)
        sys_band.addWidget(dn_panel, 44)

        # ---- TOP 进程双表并排 ----
        self.proc_model_cpu = ProcessTableModel(TOP_HEADERS)
        self.proc_model_mem = ProcessTableModel(TOP_HEADERS)
        top_row = QHBoxLayout()
        top_row.setSpacing(6)
        left = QVBoxLayout()
        left.setSpacing(2)
        left.addWidget(section_title("进程 · CPU 前十"))
        left.addWidget(_table(self.proc_model_cpu, 4, cap_rows=10))
        right = QVBoxLayout()
        right.setSpacing(2)
        right.addWidget(section_title("进程 · 内存前十"))
        right.addWidget(_table(self.proc_model_mem, 4, cap_rows=10))
        top_row.addLayout(left, 1)
        top_row.addLayout(right, 1)

        # ---- 组装 ----
        content = QWidget()
        content.setStyleSheet("background:transparent;")
        v = QVBoxLayout(content)
        v.setContentsMargins(14, 10, 14, 12)
        v.setSpacing(6)
        v.addLayout(head)
        v.addWidget(section_title("GPU"))
        v.addWidget(self.gpu_grid_host)
        v.addWidget(section_title("占卡进程"))
        v.addWidget(self.gpu_table)
        v.addWidget(section_title("系统"))
        v.addLayout(sys_band)
        v.addLayout(top_row)
        v.addStretch(1)
        self.empty_label = QLabel("在侧边栏选择一台服务器")
        self.empty_label.setAlignment(Qt.AlignCenter)
        outer = QVBoxLayout()
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(content, 1)
        outer.addWidget(self.empty_label, 1)
        wrapper = QWidget()
        wrapper.setLayout(outer)
        self.setWidget(wrapper)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._content = content

    # ------------------------------------------------------------------
    def _clear_dn_rows(self):
        """清空磁盘/网络逐行区（跨服务器切换时防数据污染）。

        行是 QWidget（整行销毁，不残留控件叠印）。"""
        while self.dn_lay.count():
            item = self.dn_lay.takeAt(0)
            w = item.widget() if item else None
            if w is not None:
                w.deleteLater()
        self.disk_rows.clear()
        self.net_rows.clear()

    def show_server(self, state: dict | None):
        """切换服务器：重置表格选择与滚动（sidebar/open_server 调用）。"""
        self.update_state(state)
        if state is None:
            return
        self.gpu_table.scrollToTop()
        self.gpu_table.clearSelection()

    def update_state(self, state: dict | None):
        self.empty_label.setVisible(state is None)
        self._content.setVisible(state is not None)
        if state is None:
            return
        # 切换服务器：磁盘/网络逐行区按挂载点/网卡名复用，跨机会串数据——必须重建
        if getattr(self, "_last_sid", None) != state["id"]:
            self._last_sid = state["id"]
            self._clear_dn_rows()
        snap = state.get("snapshot") or {}
        host = snap.get("host", {}) or {}
        cpu = snap.get("cpu", {}) or {}
        mem = snap.get("memory", {}) or {}
        self.dot.set_color({"online": "normal", "degraded": "warning",
                            "offline": "offline"}.get(state["status"], "offline"))
        self.host_label.setText(state["name"])
        self.host_sub.setText("%s · 内核 %s · 开机 %s · %s" % (
            host.get("hostname", ""), host.get("kernel", ""),
            fmt_uptime(host.get("uptime_s")),
            host.get("os_release", "")))
        ld = "%.2f / %.2f / %.2f" % (cpu.get("load1", 0), cpu.get("load5", 0),
                                      cpu.get("load15", 0))
        self.load_label.setText(ld)
        self.load_detail.setText("负载 " + ld)
        self.cores_label.setText("%d 核 · 每核利用率" % cpu.get("cores", 0))
        util_total = cpu.get("utilization_total")
        self.cpu_big.setText("%s%%" % ("--" if util_total is None
                                       else "%.1f" % util_total))
        from gpuviewer_client.ui.widgets import _level_color
        self.cpu_big.setStyleSheet(
            "color:%s; font-size:20pt; font-family:%s; font-weight:600;"
            "background:transparent"
            % (_level_color(util_total, 80.0, 95.0).name(), "Consolas"))
        self.cpu_ring.set_value(util_total)

        # GPU 瓷砖
        gpus = snap.get("gpus", [])
        while len(self.gpu_tiles) < len(gpus):
            tile = GpuTile()
            self.gpu_tiles.append(tile)
            i = len(self.gpu_tiles) - 1
            self.gpu_grid.addWidget(tile, i // 4, i % 4)
        for tile in self.gpu_tiles[len(gpus):]:
            tile.setVisible(False)
        for tile in self.gpu_tiles[: len(gpus)]:
            tile.setVisible(True)
        model = ""
        names = {g.get("name", "") for g in gpus}
        if len(names) == 1:
            model = next(iter(names)).replace("NVIDIA ", "").replace(
                "GeForce ", "")          # 同型多卡时瓷砖显示型号（一次去重）
        for tile, g in zip(self.gpu_tiles, gpus):
            tile.update_gpu(g, model=model)

        # 占卡进程（全量列出，表格高度随行数伸展；列对标 nvitop：
        # SM%/带宽% 来自 pmon，CPU%/宿主内存来自 ps，显存占比按卡总量计算）
        procs = snap.get("gpu_processes", [])
        totals = {g.get("index"): g.get("mem_total") for g in gpus}

        def _row(p):
            mem_mb = p.get("gpu_mem_mb")
            total = totals.get(p.get("gpu_index"))
            pct = ("%.0f%%" % (mem_mb / total * 100.0)
                   if mem_mb is not None and total else "--")
            cpu = p.get("cpu_pct")
            rss = p.get("host_mem_kb")
            sm, bw = p.get("sm_pct"), p.get("mem_bw_pct")
            return (p["pid"], p["user"], "GPU%s" % p.get("gpu_index"),
                    "%.0fM" % (mem_mb or 0), pct,
                    "--" if sm is None else "%.0f" % sm,
                    "--" if bw is None else "%.0f" % bw,
                    "--" if cpu is None else "%.1f" % cpu,
                    "--" if rss is None else "%.1fG" % (rss / 2 ** 20),
                    p.get("elapsed", ""), p["command"])

        self.gpu_model.set_rows([_row(p) for p in procs])
        self.gpu_table.setMinimumHeight(30 + 22 * max(3, min(len(procs), 14)))

        # 每核阵（80 核 → 40 列 × 2 行）
        per_core = cpu.get("utilization_per_core", [])
        while len(self.core_bars) < len(per_core):
            self.core_bars.append(CoreBar())
        cols = 40 if len(per_core) > 40 else max(1, len(per_core))
        for i, bar in enumerate(self.core_bars[: len(per_core)]):
            if bar.parent() is not self.core_host:
                self.core_lay.addWidget(bar, i // cols, i % cols)
            bar.set_value(per_core[i])
        for bar in self.core_bars[len(per_core):]:
            bar.setParent(None)

        # 内存
        if mem.get("total"):
            pct = mem.get("used", 0) * 100.0 / mem["total"]
            self.mem_bar.set_value(pct)
            self.mem_pct.setText("%.1f%%" % pct)
            from gpuviewer_client.ui.widgets import _level_color
            self.mem_pct.setStyleSheet(
                "color:%s; font-size:20pt; font-family:%s; font-weight:600;"
                "background:transparent"
                % (_level_color(pct).name(), "Consolas"))
            self.mem_label.setText("%s / %s" % (
                fmt_bytes(mem.get("used")), fmt_bytes(mem.get("total"))))
        if mem.get("swap_total"):
            sp = mem.get("swap_used", 0) * 100.0 / mem["swap_total"]
            self.swap_bar.set_value(sp)
            self.swap_label.setText("Swap %s / %s" % (
                fmt_bytes(mem.get("swap_used")), fmt_bytes(mem.get("swap_total"))))
        else:
            self.swap_label.setText("Swap —")
        self.cached_label.setText("缓存 %s" % fmt_bytes(mem.get("cached")))

        # 磁盘 + 网络逐行（客户端兜底过滤伪挂载：探针已滤大部分）
        skip_prefix = ("/run/", "/sys/", "/proc/", "/dev/", "/snap")
        live_mounts = set()
        for d in snap.get("disks", []):
            mount = d["mount"]
            if mount.startswith(skip_prefix) or (d.get("total", 0) < (1 << 30)
                                                 and d.get("pct", 0) == 0):
                continue
            live_mounts.add(mount)
            row = self.disk_rows.get(mount)
            if row is None:
                shown = mount if len(mount) <= 26 else mount[:24] + "…"
                name = _styled(QLabel(shown), "sub", 10)
                name.setToolTip(mount)
                bar = MiniBar()
                val = _styled(QLabel(""), "sub", 10, mono=True)
                roww = QWidget()
                h = QHBoxLayout(roww)
                h.setContentsMargins(0, 0, 0, 0)
                h.setSpacing(6)
                h.addWidget(name, 22)
                h.addWidget(bar, 40)
                h.addWidget(val, 38)
                self.dn_lay.addWidget(roww)     # 行=控件（可整行销毁，防残留叠印）
                row = self.disk_rows[mount] = (name, bar, val, roww)
            pct = d.get("pct", 0)
            row[1].set_value(pct)
            row[2].setText("%.1f%% · 剩余 %s" % (pct, fmt_bytes(d.get("avail"))))
        live_ifaces = set()
        for i in snap.get("net", []):
            live_ifaces.add(i["name"])
            row = self.net_rows.get(i["name"])
            if row is None:
                roww = QWidget()
                h = QHBoxLayout(roww)
                h.setContentsMargins(0, 0, 0, 0)
                h.setSpacing(6)
                h.addWidget(_styled(QLabel(i["name"]), "sub", 10), 22)
                lab = _styled(QLabel(""), "sub", 10, mono=True)
                h.addWidget(lab, 78)
                self.dn_lay.addWidget(roww)
                row = self.net_rows[i["name"]] = (lab, roww)
            row[0].setText("↓ %s/s   ↑ %s/s" % (
                fmt_bytes(i.get("rx_rate", 0)), fmt_bytes(i.get("tx_rate", 0))))
        # 快照中消失的挂载点/网卡（探针 st_dev 去重、卸载）→ 行即除；
        # 空快照（离线降级）视为"无数据"而非"无盘"，不动现有行。
        if snap.get("disks"):
            for m in [m for m in self.disk_rows if m not in live_mounts]:
                roww = self.disk_rows.pop(m)[3]
                self.dn_lay.removeWidget(roww)
                roww.setParent(None)
                roww.deleteLater()
        if snap.get("net"):
            for n in [n for n in self.net_rows if n not in live_ifaces]:
                roww = self.net_rows.pop(n)[1]
                self.dn_lay.removeWidget(roww)
                roww.setParent(None)
                roww.deleteLater()

        # TOP 双表
        self.proc_model_cpu.set_rows([
            (p["pid"], p["user"], "%.1f" % p["cpu"], "%.0fM" % p["mem"], p["command"])
            for p in snap.get("top_cpu", [])])
        self.proc_model_mem.set_rows([
            (p["pid"], p["user"], "%.1f" % p["cpu"], "%.0fM" % p["mem"], p["command"])
            for p in snap.get("top_mem", [])])
