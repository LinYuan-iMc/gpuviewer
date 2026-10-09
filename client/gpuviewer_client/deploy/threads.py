"""QThread 包装：DeployThread 执行部署工作流；PrecheckThread 做单机连通性预检。

信号从工作线程 emit，Qt 自动排队投递到 GUI 线程（同 Poller 模式）。
"""
import asyncio
import re

from PySide6.QtCore import QThread, Signal

from gpuviewer_client.deploy.ssh import SshSession
from gpuviewer_client.deploy.tasks import DeployWorkflow, ServerSpec


class DeployThread(QThread):
    step = Signal(str)
    log = Signal(str)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, master: ServerSpec, others: list, parent=None):
        super().__init__(parent)
        self._master = master
        self._others = others
        self._workflow = None

    def cancel(self):
        if self._workflow is not None:
            self._workflow.cancel()

    def run(self):
        async def _run():
            session = SshSession(self._master.host, self._master.port,
                                 self._master.user, self._master.password)
            self._workflow = DeployWorkflow(
                self._master, self._others, session,
                on_step=self.step.emit, on_log=self.log.emit)
            try:
                return await self._workflow.run()
            finally:
                try:
                    await session.close()
                except Exception:                                # noqa: BLE001
                    pass

        try:
            self.done.emit(asyncio.run(_run()))
        except Exception as e:                                   # noqa: BLE001
            self.failed.emit(str(e))


class PrecheckThread(QThread):
    """向导「测试连接」：认证 + python>=3.9 + base64 + nvidia-smi 探测。"""
    ok = Signal(str)
    failed = Signal(str)

    def __init__(self, spec: ServerSpec, parent=None):
        super().__init__(parent)
        self._spec = spec

    def run(self):
        async def _run():
            s = SshSession(self._spec.host, self._spec.port,
                           self._spec.user, self._spec.password)
            try:
                code, out, err = await s.run(
                    "python3 -c 'import sys; print(sys.version.split()[0])'")
                if code != 0:
                    raise RuntimeError("无 python3：%s" % (err.strip() or "命令失败"))
                ver = out.strip().splitlines()[-1]
                m = re.match(r"(\d+)\.(\d+)", ver)
                if not m or (int(m.group(1)), int(m.group(2))) < (3, 9):
                    raise RuntimeError(f"Python {ver} 低于 3.9")
                code, out, _ = await s.run(
                    "echo aGk= | base64 -d >/dev/null 2>&1 && echo ok || echo no")
                if code != 0 or out.strip() != "ok":
                    raise RuntimeError("缺少 base64 命令（daemon 远程采集依赖它）")
                code, out, _ = await s.run(
                    "command -v nvidia-smi >/dev/null 2>&1 && echo yes || echo no")
                gpu = ("nvidia-smi ✓" if code == 0 and out.strip() == "yes"
                       else "未检出 nvidia-smi（GPU 指标将为空）")
                return f"连接成功 · Python {ver} · {gpu}"
            finally:
                try:
                    await s.close()
                except Exception:                                # noqa: BLE001
                    pass

        try:
            self.ok.emit(asyncio.run(_run()))
        except Exception as e:                                   # noqa: BLE001
            self.failed.emit(str(e))
