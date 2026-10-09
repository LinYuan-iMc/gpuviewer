"""设置对话框：连接参数与告警阈值编辑，保存后由主窗热重启轮询。"""
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLineEdit,
    QWidget,
)


class SettingsDialog(QDialog):
    def __init__(self, settings, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self._s = settings
        form = QFormLayout(self)
        self.url_edit = QLineEdit(settings.base_url)
        self.url_edit.setMinimumWidth(300)     # http:// 前缀不被挤出可视区
        self.token_edit = QLineEdit(settings.token)
        self.token_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.interval_spin = QDoubleSpinBox()
        self.interval_spin.setRange(0.5, 60.0)   # 下限 0.5s：匹配 1s 采集（探针自身 ~0.7-1.2s）
        self.interval_spin.setSingleStep(0.5)
        self.interval_spin.setDecimals(1)
        self.interval_spin.setValue(float(settings.interval_s))
        self.disk_spin = QDoubleSpinBox()
        self.disk_spin.setRange(50.0, 100.0)
        self.disk_spin.setValue(float(settings.disk_warn_pct))
        self.temp_spin = QDoubleSpinBox()
        self.temp_spin.setRange(50.0, 110.0)
        self.temp_spin.setValue(float(settings.gpu_temp_warn))
        form.addRow("守护进程地址", self.url_edit)
        form.addRow("Token", self.token_edit)
        form.addRow("刷新间隔（秒）", self.interval_spin)
        form.addRow("磁盘告警阈值 %", self.disk_spin)
        form.addRow("GPU 温度告警 ℃", self.temp_spin)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save |
                                   QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)     # Save 按钮 → accept
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.accepted.connect(self._save)         # accept（按钮或编程式）统一走保存

    def _save(self):
        self._s.base_url = self.url_edit.text().strip()
        self._s.token = self.token_edit.text().strip()
        self._s.interval_s = float(self.interval_spin.value())
        self._s.disk_warn_pct = float(self.disk_spin.value())
        self._s.gpu_temp_warn = float(self.temp_spin.value())
        self._s.save()
