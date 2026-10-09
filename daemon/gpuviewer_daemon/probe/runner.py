"""探针执行器：同一份 b64 载荷，local=子进程，ssh=asyncssh。"""
import asyncio
import base64
import json
import sys
from pathlib import Path

_PROBE_SRC = (Path(__file__).parent / "probe_script.py").read_text(encoding="utf-8")
PROBE_B64 = base64.b64encode(_PROBE_SRC.encode("utf-8")).decode("ascii")
_LOCAL_CODE = "import base64;exec(base64.b64decode('{b64}'))".format(b64=PROBE_B64)


def _remote_cmd(top_n: int) -> str:
    # 管道后追加参数：python3 从 stdin(-) 读代码时，`-` 之后的 argv 透传给脚本
    return "echo {b64} | base64 -d | python3 - {n}".format(b64=PROBE_B64, n=int(top_n))


class ProbeError(Exception):
    pass


def _decode(stdout: str) -> dict:
    try:
        data = json.loads(stdout)
    except ValueError:
        raise ProbeError("probe output is not JSON: %.80r" % stdout)
    if not isinstance(data, dict) or "ts" not in data:
        raise ProbeError("probe output missing ts")
    return data


class LocalRunner:
    def __init__(self, top_n: int = 10):
        self._top_n = top_n

    async def _exec(self, payload_code: str, timeout: float) -> str:
        # -c 代码后的 argv 会成为被 exec 探针的 sys.argv[1]（即 top_n）
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-c", payload_code, str(self._top_n),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()                          # reap 子进程，消除 Proactor transport 未清理噪音
            raise ProbeError("probe timeout")
        if proc.returncode != 0:
            raise ProbeError("probe exit %d: %.200r" % (proc.returncode, err))
        return out.decode("utf-8", "replace")

    async def run(self, timeout: float = 10.0) -> dict:
        return _decode(await self._exec(_LOCAL_CODE, timeout))

    async def close(self):
        pass


class SshRunner:
    def __init__(self, entry, accept_host_keys: bool = True, top_n: int = 10):
        self._entry = entry
        self._accept = accept_host_keys
        self._top_n = top_n
        self._conn = None
        self._lock = asyncio.Lock()

    async def _ensure_conn(self):
        if self._conn is None:
            import asyncssh
            e = self._entry
            kwargs = dict(host=e.host, port=e.port or 22, username=e.user)
            if self._accept:
                # 已知取舍：无条件接受任意主机密钥（非 TOFU），仅建议内网受控环境使用
                kwargs["known_hosts"] = None
            # accept=False 时省略 known_hosts → asyncssh 默认 ~/.ssh/known_hosts 严格校验
            if e.auth == "key" and e.key_path:
                kwargs["client_keys"] = e.key_path
            else:
                kwargs["password"] = e.password
            # 不读 ~/.ssh/config：asyncssh 按系统默认编码打开它，GBK locale
            # 下解析含 UTF-8 注释的 config 会 UnicodeDecodeError（连接即炸）
            kwargs["config"] = []
            self._conn = await asyncssh.connect(**kwargs)
        return self._conn

    async def run(self, timeout: float = 10.0) -> dict:
        async with self._lock:
            try:
                conn = await self._ensure_conn()
                result = await asyncio.wait_for(
                    conn.run(_remote_cmd(self._top_n), timeout=timeout), timeout + 2)
            except ProbeError:
                raise
            except Exception as e:                      # 含 asyncssh.* 与 OSError
                await self._drop_conn()
                raise ProbeError("ssh: %s" % e)
        if result.exit_status != 0:
            raise ProbeError("remote exit %d: %.200r" % (result.exit_status, result.stderr))
        return _decode(result.stdout)

    async def _drop_conn(self):
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    async def close(self):
        await self._drop_conn()


def make_runner(entry, accept_host_keys: bool = True,
                top_n: int = 10) -> LocalRunner | SshRunner:
    return (LocalRunner(top_n=top_n) if entry.transport == "local"
            else SshRunner(entry, accept_host_keys, top_n=top_n))
