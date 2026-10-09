"""部署工作流：纯逻辑，transport 注入（生产 SshSession，测试 FakeTransport）。

步骤：预检 → 上传载荷 → 写配置 → 安装（复用 deploy_remote.sh）→ 健康检查。
复用模式：远端已有 config.toml 时保留原 token 与配置（历史数据连续），仅升级代码。
"""
import asyncio
import base64
import re
import secrets
from dataclasses import dataclass, field

from gpuviewer_client.deploy.payload import build_manifest
from gpuviewer_client.deploy.remote_config import AppConfig, DaemonConfig, ServerEntry, dump_config

REMOTE_DIR = "gpuviewer"
HTTP_PORT = 7421
INSTALL_TIMEOUT = 900.0        # venv + pip install 在慢网/慢盘上可达数分钟


class DeployError(Exception):
    pass


@dataclass
class ServerSpec:
    name: str
    host: str
    port: int = 22
    user: str = ""
    password: str = ""


@dataclass
class DeployResult:
    base_url: str
    token: str
    master_id: str
    master_name: str
    reused: bool = False
    nohup_fallback: bool = False
    notes: list[str] = field(default_factory=list)


def make_id(name: str, host: str, taken: set[str]) -> str:
    base = re.sub(r"[^a-zA-Z0-9_-]+", "-", name.strip()).strip("-").lower() or host.lower()
    sid, n = base, 2
    while sid in taken:
        sid, n = f"{base}-{n}", n + 1
    taken.add(sid)
    return sid


def generate_token() -> str:
    # 与 deploy_remote.sh 同形：24 随机字节 base64 去 /+=，纯字母数字落 TOML 无转义烦恼
    return re.sub(r"[^A-Za-z0-9]", "", base64.b64encode(secrets.token_bytes(24)).decode())


def _parse_local_id(config_text: str) -> str:
    """复用模式下从已有 config.toml 找 local 条目的 id（找不到返回空串）。"""
    for block in config_text.split("[[servers]]")[1:]:
        m_id = re.search(r'^id\s*=\s*"([^"]+)"', block, re.M)
        if m_id and re.search(r'^transport\s*=\s*"local"', block, re.M):
            return m_id.group(1)
    return ""


def default_health_get(base_url: str, token: str) -> dict:
    import requests
    r = requests.get(base_url.rstrip("/") + "/api/health",
                     headers={"Authorization": "Bearer " + token}, timeout=4)
    r.raise_for_status()
    return r.json()


class DeployWorkflow:
    def __init__(self, master: ServerSpec, others: list[ServerSpec], transport, *,
                 interval_s: float = 1.0, http_port: int = HTTP_PORT,
                 remote_dir: str = REMOTE_DIR, health_get=None, health_tries: int = 25,
                 on_step=None, on_log=None):
        self.master = master
        self.others = others
        self.t = transport
        self._interval_s = interval_s
        self._http_port = http_port
        self._rd = remote_dir
        self._health_get = health_get or default_health_get
        self._health_tries = health_tries
        self._on_step = on_step
        self._on_log = on_log
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def _chk(self):
        if self._cancelled:
            raise DeployError("部署已取消")

    def _step(self, name: str):
        if self._on_step:
            self._on_step(name)

    def _log(self, line: str):
        if self._on_log:
            self._on_log(line)

    async def run(self) -> DeployResult:
        master = self.master
        notes: list[str] = []

        # ① 预检
        self._step("连接与预检")
        code, out, err = await self.t.run(
            "python3 -c 'import sys; print(sys.version.split()[0])'")
        if code != 0:
            raise DeployError("服务器无 python3 或不可执行：%s" % (err.strip() or out.strip() or "未知错误"))
        ver = (out.strip().splitlines() or ["?"])[-1]
        m = re.match(r"(\d+)\.(\d+)", ver)
        if not m or (int(m.group(1)), int(m.group(2))) < (3, 9):
            raise DeployError(f"服务器 Python 版本过低：{ver}（需要 >= 3.9）")
        code, out, _ = await self.t.run("command -v nvidia-smi >/dev/null 2>&1 && echo yes || echo no")
        has_gpu = code == 0 and out.strip() == "yes"
        if not has_gpu:
            notes.append("总服务端未检出 nvidia-smi，本机 GPU 指标将为空（其余服务器不受影响）")
        code, out, _ = await self.t.run('printf %s "$HOME"')
        home = out.strip()
        if code != 0 or not home.startswith("/"):
            raise DeployError("无法确定远端主目录（$HOME）")
        base = f"{home}/{self._rd}"
        self._log(f"预检通过：Python {ver} · {master.user}@{master.host}"
                  + (" · nvidia-smi ✓" if has_gpu else ""))

        # ② 上传载荷
        self._step("上传代码")
        manifest = build_manifest()
        for rel, data, mode in manifest:
            self._chk()
            await self.t.write_file(f"{base}/{rel}", data, mode)
        self._log(f"已上传 {len(manifest)} 个文件 → {base}/")

        # ③ 写配置
        self._step("写入配置")
        token = None
        master_id = ""
        reused = False
        if await self.t.exists(f"{base}/config.toml"):
            raw = await self.t.read_file(f"{base}/config.toml")
            m = re.search(rb'^token\s*=\s*"([^"]+)"', raw or b"", re.M)
            if not m:
                raise DeployError("远端已有 config.toml 但读不到 token；请在服务器上检查该文件")
            token = m.group(1).decode()
            master_id = _parse_local_id((raw or b"").decode("utf-8", "replace"))
            reused = True
            self._log("检测到已有部署：复用现有 token 与配置（历史数据保留），仅升级代码")
        else:
            token = generate_token()
            taken: set[str] = set()
            master_id = make_id(master.name, master.host, taken)
            entries = [ServerEntry(id=master_id, name=master.name,
                                   transport="local", enabled=True)]
            for o in self.others:
                entries.append(ServerEntry(id=make_id(o.name, o.host, taken), name=o.name,
                                           transport="ssh", enabled=True, host=o.host,
                                           port=o.port or 22, user=o.user,
                                           auth="password", password=o.password))
            cfg = AppConfig(daemon=DaemonConfig(token=token, interval_s=self._interval_s),
                            servers=entries)
            await self.t.write_file(f"{base}/config.toml", dump_config(cfg).encode(), 0o600)
            self._log(f"已生成 config.toml：{master.name}（总服务端）+ {len(self.others)} 台 SSH 采集机")

        # ④ 安装
        self._step("安装依赖并启动服务")
        self._log("远端安装中（建 venv / 装依赖可能需要一两分钟）…")
        code, out, err = await self.t.run(f'cd "{base}" && bash deploy_remote.sh',
                                          timeout=INSTALL_TIMEOUT)
        tail = "\n".join((out or err).strip().splitlines()[-8:])
        if tail:
            self._log(tail)
        nohup_fallback = False
        if code == 3:                        # systemd 不可用 → nohup 兜底（脚本约定）
            self._log("systemd 用户服务不可用，改用 nohup 兜底启动")
            code, out, err = await self.t.run(f'cd "{base}" && bash start_nohup.sh', timeout=60)
            if code != 0:
                raise DeployError("nohup 兜底启动失败：\n" + (out or err).strip())
            nohup_fallback = True
        elif code != 0:
            raise DeployError(f"远端安装失败（exit {code}）：\n" + (out or err).strip())
        if nohup_fallback:
            notes.append("服务以 nohup 兜底运行：全部 SSH 会话退出后可能停止，"
                         "建议请管理员执行 sudo loginctl enable-linger <用户>")
        else:
            notes.append("提示：若需退出所有 SSH 会话后服务仍保活，"
                         "请管理员执行一次 sudo loginctl enable-linger <用户>")

        # ⑤ 健康检查
        self._step("健康检查")
        base_url = f"http://{master.host}:{self._http_port}"
        last_err = ""
        for i in range(self._health_tries):
            self._chk()
            try:
                info = await asyncio.to_thread(self._health_get, base_url, token)
                self._log(f"daemon 在线（v{info.get('version', '?')}，启动 "
                          f"{info.get('uptime_s', '?')}s）")
                return DeployResult(base_url=base_url, token=token, master_id=master_id,
                                    master_name=master.name, reused=reused,
                                    nohup_fallback=nohup_fallback, notes=notes)
            except Exception as e:                               # noqa: BLE001
                last_err = str(e)
                if i < self._health_tries - 1:
                    await asyncio.sleep(1.0)
        raise DeployError(
            f"服务已部署但 {base_url} 不可达（{last_err}）。"
            "请检查服务器防火墙放行 {0}/tcp（如 ufw）或本机网络可达性。".format(self._http_port))
