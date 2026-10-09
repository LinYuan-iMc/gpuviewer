#!/usr/bin/env python3
"""从真实 GPU 服务器采集只读系统指标，存为黄金测试 fixtures。

用法（密码只从环境变量 GPUVIEWER_SSH_PASS 读取，命令行不传、绝不入库；
未设置时回退到 getpass 交互输入）::

    GPUVIEWER_SSH_PASS='...' python scripts/capture_fixtures.py --host 192.168.1.10 --user user1

产物布局（host 中的点替换为下划线）::

    tests/fixtures/real/<host>/proc/
        stat  meminfo  mounts  net/dev  loadavg  uptime  os-release  passwd
        nvidia-smi-gpu.txt  nvidia-smi-compute-apps.txt  ps-gpu.txt

均为只读系统指标文本，不含任何凭据；目标机无 nvidia-smi 时对应文件留空
（探针优雅降级为 gpus=[]）。依赖 venv 内 asyncssh。
"""
import argparse
import asyncio
import getpass
import os
from pathlib import Path

import asyncssh

# 与 tests/daemon/test_real_golden.py 消费的探针读取面一致（probe_script）
REMOTE_CMD = "; ".join([
    "cat /proc/stat", "echo ---",
    "cat /proc/meminfo", "echo ---",
    "cat /proc/mounts", "echo ---",
    "cat /proc/net/dev", "echo ---",
    "cat /proc/loadavg", "echo ---",
    "cat /proc/uptime", "echo ---",
    "grep PRETTY /etc/os-release", "echo ---",
    "cat /etc/passwd", "echo ---",
    "nvidia-smi --query-gpu=index,name,uuid,utilization.gpu,utilization.memory,"
    "memory.used,memory.total,temperature.gpu,power.draw,power.limit,fan.speed "
    "--format=csv,noheader,nounits", "echo ---",
    "(nvidia-smi --query-compute-apps=gpu_uuid,pid,process_name,used_memory "
     "--format=csv,noheader,nounits || true)",
])

SEGMENTS = ["stat", "meminfo", "mounts", "net/dev", "loadavg", "uptime",
            "os-release", "passwd", "nvidia-smi-gpu.txt", "nvidia-smi-compute-apps.txt"]


def _split_raw(raw: str):
    parts = [p.strip() for p in raw.split("---")]
    if len(parts) < len(SEGMENTS):
        raise RuntimeError("远端输出分段数 %d 少于预期 %d（SSH 会话异常？）"
                           % (len(parts), len(SEGMENTS)))
    return parts[:len(SEGMENTS)]


def _compute_app_pids(compute_apps_text: str):
    pids = []
    for line in compute_apps_text.strip().splitlines():
        cols = [c.strip() for c in line.split(",")]
        if len(cols) >= 4 and cols[1].isdigit():
            pids.append(cols[1])
    return pids


async def _run(conn, cmd: str) -> str:
    result = await conn.run(cmd, check=False)
    return result.stdout or ""


async def capture(host: str, user: str, port: int, password: str) -> Path:
    out_dir = (Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "real"
               / host.replace(".", "_") / "proc")
    async with asyncssh.connect(host, port=port, username=user, password=password,
                                known_hosts=None) as conn:
        raw = await _run(conn, REMOTE_CMD)
        parts = _split_raw(raw)
        ps_text = ""
        pids = _compute_app_pids(parts[-1])
        if pids:  # 占卡进程存在时补采 ps 元数据；否则 ps-gpu.txt 留空
            ps_text = await _run(
                conn, "ps -o pid=,user=,etime=,args= -p " + ",".join(pids))
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, content in zip(SEGMENTS, parts):
        target = out_dir / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content + "\n", encoding="utf-8", newline="\n")
    (out_dir / "ps-gpu.txt").write_text(
        ps_text if not ps_text else ps_text.rstrip("\n") + "\n", encoding="utf-8",
        newline="\n")
    return out_dir


def main():
    parser = argparse.ArgumentParser(description="采集实机 fixtures（只读系统指标）")
    parser.add_argument("--host", required=True, help="目标机 IP")
    parser.add_argument("--user", required=True, help="SSH 用户名")
    parser.add_argument("--port", type=int, default=22, help="SSH 端口（默认 22）")
    args = parser.parse_args()
    password = os.environ.get("GPUVIEWER_SSH_PASS") or getpass.getpass(
        "%s@%s 的 SSH 密码: " % (args.user, args.host))
    out = asyncio.run(capture(args.host, args.user, args.port, password))
    print("fixtures saved to %s" % out)


if __name__ == "__main__":
    main()
