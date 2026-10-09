"""GPUViewer 客户端入口：轮转日志 + 应用装配。"""
import logging
import sys
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtWidgets import QApplication

from gpuviewer_client.settings import AppSettings
from gpuviewer_client.ui.main_window import MainWindow

LOG_PATH = Path.home() / ".gpuviewer" / "client.log"


def setup_logging() -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(LOG_PATH, maxBytes=2 * 1024 * 1024,
                                  backupCount=3, encoding="utf-8")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[handler],
        force=True)
    logging.getLogger("PySide6").setLevel(logging.WARNING)

    class _StderrTee:
        """stderr 同步镜像到日志（pythonw 下 stderr 不可见；PySide6 的
        "Error calling Python override" 类异常走 stderr，不接住即无声）。"""

        def __init__(self, original):
            self._orig = original

        def write(self, s):
            if s.strip():
                logging.getLogger("gpuviewer.stderr").error(s.rstrip())
            try:
                self._orig.write(s)
            except Exception:
                pass

        def flush(self):
            try:
                self._orig.flush()
            except Exception:
                pass

    sys.stderr = _StderrTee(sys.stderr)

    def _hook(t, v, tb):
        logging.getLogger("gpuviewer.fatal").error(
            "未捕获异常:\n%s", "".join(traceback.format_exception(t, v, tb)))

    sys.excepthook = _hook


def main():
    setup_logging()
    log = logging.getLogger("gpuviewer.client")
    log.info("客户端启动")
    app = QApplication(sys.argv)
    win = MainWindow(AppSettings())
    win.show()
    win.maybe_show_wizard()          # 首启未配置 → 初始化向导（写好地址/token 再开始轮询）
    win.start_polling()
    app.aboutToQuit.connect(win.shutdown)
    code = app.exec()
    log.info("客户端退出 code=%s", code)
    sys.exit(code)


def _guarded_main():
    """pythonw 无控制台，stderr 不可见——把一切未捕获异常落盘，杜绝无声死亡。"""
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write("\n%s 客户端致命异常:\n%s\n" % (
                logging.Formatter().formatTime(
                    logging.LogRecord("fatal", 40, "", 0, "", None, None)),
                traceback.format_exc()))
        raise


if __name__ == "__main__":
    _guarded_main()
