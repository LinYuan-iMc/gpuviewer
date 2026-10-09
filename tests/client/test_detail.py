import pytest


@pytest.fixture
def page(qapp):
    from gpuviewer_client.ui.detail_page import DetailPage
    return DetailPage()


def test_detail_sections(page, client_payload):
    st = client_payload["servers"][0]
    page.update_state(st)
    assert page.host_label.text() == "L40"
    assert page.load_label.text() == "0.52 / 0.58 / 0.59"
    assert page.cpu_ring._pct == 12.5
    assert len(page.core_bars) == 2
    assert len(page.gpu_tiles) == 1
    assert page.gpu_tiles[0].util_label.text() == "87%"
    assert page.gpu_tiles[0].mem_label.text() == "33.2/45.0G"
    assert page.gpu_model.rowCount() == 1                      # 占卡进程全量
    assert page.gpu_model.data(page.gpu_model.index(0, 0)) == "12345"
    assert page.gpu_table.minimumHeight() >= 30 + 22 * 3       # 表格不再被压缩
    assert page.proc_model_cpu.rowCount() == 1
    assert "/" in page.disk_rows and "eth0" in page.net_rows
    mem_total_g = st["snapshot"]["memory"]["total"] / 2**30
    assert "%.1f" % mem_total_g in page.mem_label.text()


def test_detail_gpu_proc_full_list(qapp, make_snapshot):
    """多占卡进程必须全量列出（用户反馈：不止一行）。"""
    from gpuviewer_client.ui.detail_page import DetailPage
    snap = make_snapshot()
    snap["gpu_processes"] = [
        {"pid": 100 + i, "user": "u%d" % i, "command": "train%d" % i,
         "gpu_mem_mb": 1000.0 * i, "gpu_index": i % 8, "elapsed": "1:00"}
        for i in range(8)]
    page = DetailPage()
    page.update_state({"id": "s", "name": "S", "status": "online",
                       "last_error": None, "last_success_ts": 1,
                       "snapshot": snap})
    assert page.gpu_model.rowCount() == 8
    assert page.gpu_table.minimumHeight() == 30 + 22 * 8       # 高度随行数伸展


def test_detail_empty(page):
    page.update_state(None)
    assert not page._content.isVisibleTo(page)


def test_tables_diff_not_reset(page, client_payload):
    st = client_payload["servers"][0]
    page.update_state(st)
    st2 = client_payload["servers"][0]
    st2["snapshot"]["top_cpu"][0] = dict(st2["snapshot"]["top_cpu"][0], cpu=9.9)
    page.update_state(st2)
    assert page.proc_model_cpu.rowCount() == 1
    assert page.proc_model_cpu.data(page.proc_model_cpu.index(0, 2)) == "9.9"


def test_disk_net_rows_not_polluted_across_servers(qapp, make_snapshot):
    """切换服务器时磁盘/网络逐行区必须重建——旧服务器的行不得残留叠印。"""
    from gpuviewer_client.ui.detail_page import DetailPage

    def state(sid, snap):
        return {"id": sid, "name": sid, "status": "online", "last_error": None,
                "last_success_ts": 1, "snapshot": snap}

    s_l40 = make_snapshot()
    s_l40["disks"] = [{"mount": "/", "pct": 70.0, "used": 700, "total": 1000, "avail": 300},
                      {"mount": "/data", "pct": 50.0, "used": 5, "total": 10, "avail": 5}]
    s_l40["net"] = [{"name": "eno1np0", "rx_rate": 1.0, "tx_rate": 2.0}]
    s_4090 = make_snapshot()
    s_4090["disks"] = [{"mount": "/", "pct": 91.0, "used": 910, "total": 1000, "avail": 90},
                       {"mount": "/mnt2", "pct": 10.0, "used": 1, "total": 10, "avail": 9}]
    s_4090["net"] = [{"name": "eno9", "rx_rate": 9.0, "tx_rate": 8.0}]

    page = DetailPage()
    page.update_state(state("l40", s_l40))
    assert set(page.disk_rows) == {"/", "/data"} and set(page.net_rows) == {"eno1np0"}
    page.update_state(state("rtx4090", s_4090))
    assert set(page.disk_rows) == {"/", "/mnt2"}      # /data 已清，无残留
    assert set(page.net_rows) == {"eno9"}             # eno1np0 已清
    assert page.dn_lay.count() == 2 + 1               # 2 磁盘行 + 1 网络行，无叠印


def test_disk_rows_removed_when_mount_vanishes(qapp, make_snapshot):
    """同一服务器内，快照中消失的挂载点/网卡行必须移除（探针 st_dev 去重后行数会减）。"""
    from gpuviewer_client.ui.detail_page import DetailPage

    def state(snap):
        return {"id": "l40", "name": "L40", "status": "online",
                "last_error": None, "last_success_ts": 1, "snapshot": snap}

    snap = make_snapshot()
    snap["disks"] = [{"mount": "/", "pct": 59.7, "used": 6, "total": 10, "avail": 4},
                     {"mount": "/home/CNU", "pct": 95.2, "used": 9, "total": 10, "avail": 1},
                     {"mount": "/home/org/22/pk/shared", "pct": 95.2, "used": 9,
                      "total": 10, "avail": 1},
                     {"mount": "/var/snap/firefox/common/host-hunspell", "pct": 59.7,
                      "used": 6, "total": 10, "avail": 4}]
    snap["net"] = [{"name": "eno1np0", "rx_rate": 1.0, "tx_rate": 2.0}]
    page = DetailPage()
    page.update_state(state(snap))
    assert len(page.disk_rows) == 4

    dedup = make_snapshot()
    dedup["disks"] = [snap["disks"][0], snap["disks"][1]]   # shared/转 snap 并入
    dedup["net"] = snap["net"]
    page.update_state(state(dedup))
    assert set(page.disk_rows) == {"/", "/home/CNU"}         # 僵尸行已移除
    assert page.dn_lay.count() == 2 + 1                      # 2 磁盘 + 1 网络

    dedup2 = make_snapshot()
    dedup2["disks"] = []
    dedup2["net"] = []
    page.update_state(state(dedup2))                          # 空快照≠无盘：不动现有行
    assert set(page.disk_rows) == {"/", "/home/CNU"}


def test_gpu_proc_table_nvitop_columns(qapp, make_snapshot):
    """占卡进程表对标 nvitop：显存%/CPU%/宿主内存列。"""
    from gpuviewer_client.ui.detail_page import DetailPage

    snap = make_snapshot()
    snap["gpus"] = [{"index": 0, "name": "T", "uuid": "GPU-a",
                     "mem_total": 24564.0}]
    snap["gpu_processes"] = [{
        "pid": 42, "user": "user2", "gpu_index": 0, "gpu_mem_mb": 12282.0,
        "elapsed": "2:00", "command": "python train.py",
        "cpu_pct": 99.2, "host_mem_pct": 4.1, "host_mem_kb": 2097152.0,
        "sm_pct": 87.0, "mem_bw_pct": 4.0}]
    page = DetailPage()
    page.update_state({"id": "s", "name": "S", "status": "online",
                       "last_error": None, "last_success_ts": 1,
                       "snapshot": snap})
    assert page.gpu_model.columnCount() == 11
    r = [page.gpu_model.data(page.gpu_model.index(0, c))
         for c in range(page.gpu_model.columnCount())]
    assert r[4] == "50%"                                  # 显存% = 12282/24564
    assert r[5] == "87"                                   # SM%
    assert r[6] == "4"                                    # 带宽%
    assert r[7] == "99.2"                                 # CPU%
    assert r[8] == "2.0G"                                 # 宿主内存
    # 旧载荷（无新字段）不炸，显示 --
    for k in ("cpu_pct", "host_mem_kb", "sm_pct", "mem_bw_pct"):
        snap["gpu_processes"][0].pop(k)
    page.update_state({"id": "s", "name": "S", "status": "online",
                       "last_error": None, "last_success_ts": 1,
                       "snapshot": snap})
    r2 = [page.gpu_model.data(page.gpu_model.index(0, c))
          for c in range(page.gpu_model.columnCount())]
    assert r2[5] == "--" and r2[6] == "--" and r2[7] == "--"


def test_gpu_table_scrollable_when_narrow(qapp, qtbot, make_snapshot):
    """窄窗口：命令列不得被挤没，横向滚动条必须可用（11 列溢出场景）。"""
    from gpuviewer_client.ui.detail_page import DetailPage

    snap = make_snapshot()
    snap["gpus"] = [{"index": i, "name": "T", "uuid": "GPU-%d" % i,
                     "mem_total": 24564.0} for i in range(8)]
    snap["gpu_processes"] = [{
        "pid": 1000 + i, "user": "user2", "gpu_index": i % 8,
        "gpu_mem_mb": 12282.0, "elapsed": "3-05:41:27",
        "command": "python /very/long/path/train.py --epochs 100 --lr 3e-4",
        "cpu_pct": 5.0, "host_mem_kb": 2097152.0} for i in range(8)]
    page = DetailPage()
    page.update_state({"id": "s", "name": "S", "status": "online",
                       "last_error": None, "last_success_ts": 1,
                       "snapshot": snap})
    # 600px 宽窗下 11 列（合计 ~844px）大幅溢出，断言余量充足；900px 时余量
    # 仅 4px，滚动条宽度等 ±十几像素的环境差异即假失败
    page.resize(600, 800)
    page.show()
    qtbot.waitExposed(page, timeout=5000)
    cmd_col = page.gpu_model.columnCount() - 1
    qtbot.waitUntil(lambda: (page.gpu_table.horizontalScrollBar().maximum() > 100
                             and page.gpu_table.columnWidth(cmd_col) >= 300),
                    timeout=5000)
    assert page.gpu_table.columnWidth(cmd_col) >= 300   # 命令列不被挤没
    assert page.gpu_table.horizontalScrollBar().maximum() > 100  # 可横向滚动
    page.hide()
