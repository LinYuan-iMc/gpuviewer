"""悬浮预览：截断标签全文 tooltip、表格 ToolTipRole、GPU 控件富 tooltip。"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel


def test_table_tooltip_role(qapp):
    """表格单元格悬浮返回全文（命令列截断时悬浮可见完整命令行）。"""
    from gpuviewer_client.models import ProcessTableModel

    m = ProcessTableModel(["PID", "CMD"])
    m.set_rows([("1", "python train.py --lr 3e-4 --epochs 100 --data /home/org/ds")])
    assert m.data(m.index(0, 1), Qt.ItemDataRole.ToolTipRole) == \
        "python train.py --lr 3e-4 --epochs 100 --data /home/org/ds"
    assert m.data(m.index(0, 1), Qt.ItemDataRole.DisplayRole) == \
        m.data(m.index(0, 1), Qt.ItemDataRole.ToolTipRole)


def test_label_clipped_detection(qapp):
    """label_text_clipped：窄标签报截断，宽标签不报。"""
    from gpuviewer_client.ui.widgets import label_text_clipped

    lbl = QLabel("/home/org/22/pk/shared/projects/long/path")
    lbl.setFixedWidth(60)
    assert label_text_clipped(lbl)
    lbl2 = QLabel("/")
    lbl2.setFixedWidth(200)
    assert not label_text_clipped(lbl2)
    lbl3 = QLabel("")                       # 空文本永不截断
    assert not label_text_clipped(lbl3)


def test_elide_filter_routes_to_preview(qapp):
    """过滤器：截断标签的 ToolTip 事件被消费并路由到 HoverPreview；
    完整文本/无 tooltip 的不路由。"""
    from gpuviewer_client.ui.widgets import ElideTipFilter, HoverPreview
    from PySide6.QtCore import QEvent, QPoint
    from PySide6.QtGui import QHelpEvent

    f = ElideTipFilter()
    lbl = QLabel("/home/org/22/pk/shared/projects")
    lbl.setFixedWidth(50)
    e = QHelpEvent(QEvent.Type.ToolTip, QPoint(1, 1), QPoint(100, 100))
    assert f.eventFilter(lbl, e) is True          # 消费并路由
    assert HoverPreview.instance().label().text() == lbl.text()

    wide = QLabel("/")
    wide.setFixedWidth(300)
    assert f.eventFilter(wide, QHelpEvent(
        QEvent.Type.ToolTip, QPoint(1, 1), QPoint(1, 1))) is False


def test_gpu_chip_rich_tooltip(qapp):
    from gpuviewer_client.ui.widgets import GpuChip

    c = GpuChip()
    c.update_gpu({"index": 2, "name": "NVIDIA GeForce RTX 4090",
                  "utilization": 87.0, "temperature": 66,
                  "mem_used": 20240.0, "mem_total": 24564.0})
    tip = c.toolTip()
    assert "GPU2" in tip and "RTX 4090" in tip
    assert "87%" in tip and "66℃" in tip and "显存" in tip


def test_gpu_tile_rich_tooltip(qapp):
    from gpuviewer_client.ui.widgets import GpuTile

    t = GpuTile()
    t.update_gpu({"index": 0, "name": "NVIDIA L40", "utilization": 12.0,
                  "temperature": 41, "mem_used": 44000.0, "mem_total": 46000.0,
                  "power_draw": 121.4, "power_limit": 300.0}, model="L40")
    tip = t.toolTip()
    assert "GPU0 · L40" in tip and "NVIDIA L40" in tip
    assert "功耗 121W / 300W" in tip and "显存" in tip
