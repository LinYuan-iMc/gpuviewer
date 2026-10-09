"""SshSession：asyncssh 薄封装，实现 DeployWorkflow 所需的 Transport 协议。

认证与连接姿态照抄 daemon probe/runner.py：内网场景 known_hosts=None（接受
任意主机指纹）、密码认证、出错即断连重连。惰性 import asyncssh，客户端
未装该依赖时其余功能不受影响。
"""
import asyncio


class SshSession:
    SFTP_TIMEOUT = 60.0        # 单次 SFTP 操作上限——连接异常时必须报错而非永久挂死

    def __init__(self, host: str, port: int = 22, user: str = "", password: str = "",
                 connect_timeout: float = 15.0):
        self.host = host
        self.port = port or 22
        self.user = user
        self.password = password
        self._connect_timeout = connect_timeout
        self._conn = None
        self._sftp = None

    async def _ensure(self):
        if self._conn is None:
            import asyncssh
            self._conn = await asyncssh.connect(
                self.host, port=self.port, username=self.user,
                password=self.password, known_hosts=None,
                connect_timeout=self._connect_timeout,
                # 不读 ~/.ssh/config：asyncssh 以系统默认编码打开它，中文
                # Windows（GBK）下解析含 UTF-8 注释的 config 直接
                # UnicodeDecodeError——连接未开始即炸（实测 byte 0xa8 卡死）
                config=[])
        return self._conn

    async def _sftp_client(self):
        if self._sftp is None:
            self._sftp = await (await self._ensure()).start_sftp_client()
        return self._sftp

    async def run(self, cmd: str, timeout: float = 60.0) -> tuple[int, str, str]:
        conn = await self._ensure()
        try:
            res = await asyncio.wait_for(conn.run(cmd, timeout=timeout), timeout + 10)
        except Exception as e:                                   # noqa: BLE001
            await self.close()
            raise RuntimeError(f"SSH 执行失败（{type(e).__name__}: {e}）") from e
        return res.exit_status or 0, res.stdout or "", res.stderr or ""

    async def exists(self, path: str) -> bool:
        import asyncssh
        sftp = await self._sftp_client()
        try:
            await asyncio.wait_for(sftp.stat(path), self.SFTP_TIMEOUT)
            return True
        except asyncssh.SFTPError:
            return False
        except asyncio.TimeoutError:
            await self.close()
            raise RuntimeError(f"SFTP 超时（{self.SFTP_TIMEOUT}s）：stat {path}，连接已重置")

    async def read_file(self, path: str) -> bytes | None:
        import asyncssh
        sftp = await self._sftp_client()
        try:
            async with sftp.open(path, "rb") as f:
                return await asyncio.wait_for(f.read(), self.SFTP_TIMEOUT)
        except asyncssh.SFTPError:
            return None
        except asyncio.TimeoutError:
            await self.close()
            raise RuntimeError(f"SFTP 超时（{self.SFTP_TIMEOUT}s）：read {path}，连接已重置")

    async def write_file(self, path: str, data: bytes, mode: int = 0o644) -> None:
        import asyncssh
        sftp = await self._sftp_client()
        parts = path.strip("/").split("/")
        cur = ""
        for p in parts[:-1]:                     # 逐级 mkdir，已存在忽略
            cur += "/" + p
            try:
                await asyncio.wait_for(sftp.mkdir(cur), self.SFTP_TIMEOUT)
            except asyncssh.SFTPError:
                pass
        # 大文件（数据库备份 ~500MB）按内容大小放宽超时
        timeout = max(self.SFTP_TIMEOUT, len(data) / 2e6)
        async with sftp.open(path, "wb") as f:
            await asyncio.wait_for(f.write(data), timeout)
        await asyncio.wait_for(sftp.chmod(path, mode), self.SFTP_TIMEOUT)

    async def close(self) -> None:
        if self._sftp is not None:
            try:
                self._sftp.exit()
            except Exception:                                    # noqa: BLE001
                pass
            self._sftp = None
        if self._conn is not None:
            self._conn.close()
            await self._conn.wait_closed()
            self._conn = None
