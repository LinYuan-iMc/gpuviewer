"""跟手悬浮预览窗：快速出现、跟随光标、文本可选中复制。"""
from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QHelpEvent
from PySide6.QtWidgets import QLabel


def _tip_event():
    from PySide6.QtCore import QEvent
    return QHelpEvent(QEvent.Type.ToolTip, QPoint(1, 1), QPoint(400, 300))


def test_preview_shows_routed_tooltip(qapp):
    """过滤器把 ToolTip 事件路由到预览窗（消费事件），全文在可选中标签里。"""
    from gpuviewer_client.ui.widgets import ElideTipFilter, HoverPreview

    f = ElideTipFilter()
    lbl = QLabel("/home/org/22/pk/shared/projects")
    lbl.setFixedWidth(50)                       # 截断 → 全文预览
    assert f.eventFilter(lbl, _tip_event()) is True
    pv = HoverPreview.instance()
    assert pv.label().text() == lbl.text()

    tipped = QLabel("短")
    tipped.setToolTip("完整内容第一行\n第二行")
    assert f.eventFilter(tipped, _tip_event()) is True
    assert pv.label().text() == "完整内容第一行\n第二行"

    wide = QLabel("/")
    wide.setFixedWidth(300)                     # 不截断无 tooltip → 不路由
    assert f.eventFilter(wide, _tip_event()) is False


def test_preview_window_receives_input(qapp):
    """窗口标志必须是 Tool 而非 ToolTip——Qt.ToolTip 对鼠标输入透明，
    选中/复制不可能实现（实测踩坑）。"""
    from gpuviewer_client.ui.widgets import HoverPreview

    pv = HoverPreview.instance()
    f = int(pv.windowFlags())
    # WindowType 成员是组合值（Tool=Popup|Dialog 等），须按包含语义判断
    assert f & int(Qt.WindowType.ToolTip) != int(Qt.WindowType.ToolTip)
    assert f & int(Qt.WindowType.Tool) == int(Qt.WindowType.Tool)
    assert pv.label().focusPolicy() & Qt.FocusPolicy.StrongFocus


def test_ctrl_c_copies_selection(qapp):
    """框内选中文字后 Ctrl+C → 剪贴板获得所选文本。"""
    from gpuviewer_client.ui.widgets import HoverPreview
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QGuiApplication, QKeyEvent

    pv = HoverPreview.instance()
    pv.show_for("python train.py --lr 3e-4", QPoint(300, 300), None)
    pv.label().setSelection(0, 6)                 # 模拟拖选 "python"
    ke = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier,
                   "c")
    pv.keyPressEvent(ke)
    assert QGuiApplication.clipboard().text() == "python"
    pv.hide()


def test_table_cells_routed_via_model(qapp):
    """表格单元格：过滤器代查模型 ToolTipRole → 路由到预览窗（可复制命令行）。"""
    from gpuviewer_client.models import ProcessTableModel
    from gpuviewer_client.ui.widgets import ElideTipFilter
    from PySide6.QtWidgets import QTableView

    m = ProcessTableModel(["PID", "CMD"])
    m.set_rows([("1", "python train.py --lr 3e-4")])
    view = QTableView()
    view.setModel(m)
    view.resize(400, 60)
    view.show()
    qapp.processEvents()
    vp = view.viewport()
    cell_g = vp.mapToGlobal(vpos := vp.rect().center())
    f = ElideTipFilter()
    e = QHelpEvent(QEvent.Type.ToolTip, vpos, cell_g)
    assert f.eventFilter(vp, e) is True
    from gpuviewer_client.ui.widgets import HoverPreview
    assert HoverPreview.instance().label().text() in (
        "1", "python train.py --lr 3e-4")
    view.hide()
    HoverPreview.instance().hide()


def test_preview_text_selectable(qapp):
    """预览文本必须可鼠标选中（复制路径/命令行的核心诉求）。"""
    from gpuviewer_client.ui.widgets import HoverPreview

    flags = HoverPreview.instance().label().textInteractionFlags()
    assert flags & Qt.TextSelectableByMouse


def test_preview_follows_cursor(qapp):
    """track()：光标移动时预览窗跟随（偏移避让光标，不遮挡）。"""
    from gpuviewer_client.ui.widgets import HoverPreview

    pv = HoverPreview.instance()
    pv.show_for("GPU0\n显存 43.9/45.0G", QPoint(500, 400), None)
    p1 = pv.pos()
    pv.track(QPoint(700, 500))                  # 光标右移
    p2 = pv.pos()
    assert p2.x() > p1.x() and p2.y() > p1.y()
    # 翻转：光标贴近屏幕右下角时预览改到左上侧
    from PySide6.QtGui import QGuiApplication
    scr = QGuiApplication.primaryScreen().availableGeometry()
    pv.track(QPoint(scr.right() - 2, scr.bottom() - 2))
    p3 = pv.pos()
    assert p3.x() < scr.right() - 2 and p3.y() < scr.bottom() - 2
    pv.hide()


def test_preview_freezes_over_itself(qapp):
    """光标进入预览窗自身时停止跟随并保持显示（选中文本的前提）。"""
    from gpuviewer_client.ui.widgets import HoverPreview

    pv = HoverPreview.instance()
    pv.show_for("内容", QPoint(500, 400), None)
    center = pv.geometry().center()
    pv.track(QPoint(center.x(), center.y()))     # 光标在预览窗内
    pos_before = pv.pos()
    assert pv.isVisible()
    pv.track(QPoint(center.x() + 3, center.y() + 3))   # 仍在窗内
    assert pv.pos() == pos_before                # 冻结不跟手
    pv.hide()


def test_preview_wraps_long_commands(qapp):
    """超长命令行折行显示，宽度被钳制不溢出屏幕。"""
    from gpuviewer_client.ui.widgets import HoverPreview

    pv = HoverPreview.instance()
    long_cmd = "python train.py " + "--arg%d value%d " * 40 % tuple(
        i for i in range(80))
    pv.show_for(long_cmd, QPoint(100, 100), None)
    assert pv.label().wordWrap()
    assert pv.width() <= pv.MAX_W + 40
    pv.hide()
