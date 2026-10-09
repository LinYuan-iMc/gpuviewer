#!/usr/bin/env python3
"""GPUViewer 探针：自包含、纯标准库、兼容 Python 3.6。输出一个 JSON 快照。

所有读取函数带 base 参数（默认 "/proc"），tests/fixtures/proc 提供同名样本文件。
nvidia-smi 相关函数优先读 <base>/nvidia-smi-*.txt（测试用），否则执行真实命令。
"""
import json
import os
import subprocess
import sys
import time

PSEUDO_FS = {"proc", "sysfs", "devtmpfs", "tmpfs", "devpts", "securityfs",
             "cgroup2", "cgroup", "overlay", "squashfs", "bpf", "tracefs",
             "fusectl", "pstore", "binfmt_misc", "hugetlbfs", "mqueue",
             "debugfs", "configfs", "efivarfs", "ramfs", "nsfs", "autofs",
             "rpc_pipefs", "sunrpc", "fuse", "iso9660", "udf", "erofs"}
PSEUDO_PREFIX = ("/snap", "/boot/efi", "/run/", "/sys/", "/proc/", "/dev/")
# /run/ 前缀整体过滤：systemd credentials 等运行时挂载无监控价值


def _read(path):
    with open(path) as f:
        return f.read()


def _read_first(path_list):
    for p in path_list:
        try:
            return _read(p)
        except (IOError, OSError):
            continue
    return ""


# ---------- 主机 ----------
def read_host(base="/proc"):
    try:
        uname = os.uname()
        hostname, kernel = uname.nodename, uname.release
    except AttributeError:                      # 非 POSIX（仅测试环境）
        hostname, kernel = "", ""
    os_release = ""
    text = _read_first([base + "/os-release", "/etc/os-release"])
    for line in text.splitlines():
        if line.startswith("PRETTY_NAME="):
            os_release = line.split("=", 1)[1].strip('"')
            break
    uptime = 0.0
    text = _read(base + "/uptime")
    if text:
        uptime = float(text.split()[0])
    return {"hostname": hostname, "os_release": os_release,
            "kernel": kernel, "uptime_s": uptime}


# ---------- CPU ----------
def _parse_stat(text):
    total, cores = None, []
    for line in text.splitlines():
        parts = line.split()
        if line.startswith("cpu "):
            total = [int(x) for x in parts[1:]]
        elif line.startswith("cpu") and parts:
            cores.append([int(x) for x in parts[1:]])
    return total, cores


def _pct(a, b):
    if not a or not b:
        return 0.0
    idle_a = a[3] + (a[4] if len(a) > 4 else 0)
    idle_b = b[3] + (b[4] if len(b) > 4 else 0)
    dt = sum(b) - sum(a)
    di = idle_b - idle_a
    if dt <= 0:
        return 0.0
    return round(max(0.0, min(100.0, (dt - di) * 100.0 / dt)), 1)


def read_cpu(base="/proc", interval=0.2):
    total_a, cores_a = _parse_stat(_read(base + "/stat"))
    time.sleep(interval)
    total_b, cores_b = _parse_stat(_read(base + "/stat"))
    la = [float(x) for x in _read(base + "/loadavg").split()[:3]]
    return {"cores": len(cores_a), "utilization_total": _pct(total_a, total_b),
            "utilization_per_core": [_pct(a, b) for a, b in zip(cores_a, cores_b)],
            "load1": la[0], "load5": la[1], "load15": la[2]}


# ---------- 内存 ----------
def read_mem(base="/proc"):
    info = {}
    for line in _read(base + "/meminfo").splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        info[k] = int(v.strip().split()[0]) * 1024
    total = info.get("MemTotal", 0)
    avail = info.get("MemAvailable", info.get("MemFree", 0))
    return {"total": total, "used": max(0, total - avail), "available": avail,
            "cached": info.get("Cached", 0) + info.get("Buffers", 0),
            "swap_total": info.get("SwapTotal", 0),
            "swap_used": max(0, info.get("SwapTotal", 0) - info.get("SwapFree", 0))}


# ---------- 磁盘 ----------
def _disks_from_lines(lines, statvfs_fn, stat_fn=None):
    if stat_fn is None:
        stat_fn = os.stat
    seen, seen_dev, out = set(), set(), []
    for line in lines:
        parts = line.split()
        if len(parts) < 3:
            continue
        dev, mount, fstype = parts[0], parts[1], parts[2]
        if fstype in PSEUDO_FS or mount.startswith(PSEUDO_PREFIX):
            continue
        if (dev, mount) in seen:
            continue
        seen.add((dev, mount))
        try:
            st = statvfs_fn(mount)
        except (IOError, OSError):
            continue
        total = st.f_blocks * st.f_frsize
        avail = st.f_bavail * st.f_frsize
        used = (st.f_blocks - st.f_bfree) * st.f_frsize
        pct = round(used * 100.0 / (used + avail), 1) if (used + avail) > 0 else 0.0
        # 同一文件系统的重复挂载（bind mount 等）内核里 st_dev 相同 → 去重保首
        try:
            fsid = stat_fn(mount).st_dev
        except (IOError, OSError):
            fsid = None
        if fsid is not None:
            if fsid in seen_dev:
                continue
            seen_dev.add(fsid)
        out.append({"mount": mount, "total": total, "used": used,
                    "avail": avail, "pct": pct})
    return out


def read_disks(base="/proc"):
    return _disks_from_lines(_read(base + "/mounts").splitlines(), os.statvfs)


# ---------- 网络 ----------
def read_net(base="/proc"):
    out = []
    for line in _read(base + "/net/dev").splitlines()[2:]:
        if ":" not in line:
            continue
        name, rest = line.split(":", 1)
        name = name.strip()
        base_name = name.split("@")[0]            # veth1234@if2 → veth1234
        if base_name == "lo" or base_name.startswith(
                ("veth", "docker", "br-", "virbr", "flannel", "tunl")):
            continue
        f = rest.split()
        out.append({"name": name, "rx_bytes": int(f[0]), "tx_bytes": int(f[8])})
    return out


# ---------- GPU ----------
GPU_QUERY = ("index,name,uuid,utilization.gpu,utilization.memory,memory.used,"
             "memory.total,temperature.gpu,power.draw,power.limit,fan.speed")


def _num(s):
    if s is None:
        return None
    s = s.strip()
    if not s or s in ("[N/A]", "N/A", "[Not Supported]"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _run_or_read(cmd, fallback_path):
    if os.path.exists(fallback_path):
        return _read(fallback_path)
    try:
        out = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             timeout=5)
        if out.returncode != 0:
            return ""
        return out.stdout.decode("utf-8", "replace")
    except Exception:
        return ""


def _nvidia_launch(base):
    """并行预取三路 nvidia-smi：串行各 ~0.4-0.6s 是探针耗时主因。
    fixture 模式（gpu.txt 存在）返回 (None, None, None) 走文件路径。"""
    if os.path.exists(base + "/nvidia-smi-gpu.txt"):
        return None, None, None
    try:
        pg = subprocess.Popen(
            ["nvidia-smi", "--query-gpu=" + GPU_QUERY,
             "--format=csv,noheader,nounits"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        pp = subprocess.Popen(
            ["nvidia-smi", "--query-compute-apps=gpu_uuid,pid,process_name,"
             "used_memory", "--format=csv,noheader,nounits"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        pm = subprocess.Popen(["nvidia-smi", "pmon", "-c", "1"],
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        return pg, pp, pm
    except Exception:
        return None, None, None


def _nvidia_collect(proc, timeout=6):
    """收割预取的 Popen；失败回退空串（与旧路径的失败语义一致）。"""
    if proc is None:
        return None
    try:
        return proc.communicate(timeout=timeout)[0].decode("utf-8", "replace")
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
        return ""


def read_gpus(base="/proc", text=None):
    if text is None:
        text = _run_or_read(["nvidia-smi", "--query-gpu=" + GPU_QUERY,
                             "--format=csv,noheader,nounits"],
                            base + "/nvidia-smi-gpu.txt")
    out = []
    for line in text.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 11:
            continue
        idx = _num(parts[0])
        if idx is None:
            continue
        out.append({"index": int(idx), "name": parts[1], "uuid": parts[2],
                    "utilization": _num(parts[3]), "mem_utilization": _num(parts[4]),
                    "mem_used": _num(parts[5]), "mem_total": _num(parts[6]),
                    "temperature": _num(parts[7]), "power_draw": _num(parts[8]),
                    "power_limit": _num(parts[9]), "fan_speed": _num(parts[10])})
    return out


def _parse_pmon(text):
    """解析 `nvidia-smi pmon -c 1`：pid → (sm%, 显存带宽%)。
    行格式: gpu_idx pid type sm mem enc dec command...（# 开头为表头）。"""
    out = {}
    if not text:
        return out
    for line in text.strip().splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = line.split(None, 7)
        if len(parts) < 5 or not parts[1].isdigit():
            continue
        out[parts[1]] = (_num(parts[3]), _num(parts[4]))
    return out


def read_gpu_processes(base="/proc", gpus=None, text=None, pmon_text=None):
    gpus = gpus or []
    if text is None:
        text = _run_or_read(
            ["nvidia-smi", "--query-compute-apps=gpu_uuid,pid,process_name,used_memory",
             "--format=csv,noheader,nounits"], base + "/nvidia-smi-compute-apps.txt")
    if pmon_text is None:
        fb = base + "/nvidia-smi-pmon.txt"
        if os.path.exists(fb):
            pmon_text = _read(fb)          # fixture 优先
        elif not os.path.exists(base + "/nvidia-smi-compute-apps.txt"):
            # 实机路径才跑真实 pmon；fixture 模式无 pmon 文件即视为无数据
            pmon_text = _run_or_read(["nvidia-smi", "pmon", "-c", "1"], fb)
    pmon = _parse_pmon(pmon_text)
    rows = [[p.strip() for p in line.split(",")] for line in text.strip().splitlines()
            if line.strip()]
    if not rows:
        return []
    uuid_to_idx = {g["uuid"]: g["index"] for g in gpus}
    pids = [r[1] for r in rows if len(r) >= 4]
    ps = _run_or_read(["ps", "-o", "pid=,user=,etime=,pcpu=,pmem=,rss=,args=",
                       "-p", ",".join(pids)], base + "/ps-gpu.txt")
    meta = {}
    for line in ps.strip().splitlines():
        parts = line.strip().split(None, 6)
        if (len(parts) >= 6 and _num(parts[3]) is not None
                and _num(parts[4]) is not None and _num(parts[5]) is not None):
            # 新格式: pid user etime pcpu pmem rss args——第3-5位必为数值，
            # 以此与旧 4 字段 fixture（第3位起是命令行）消歧
            meta[parts[0]] = (parts[1], parts[2], parts[3], parts[4],
                              parts[5], parts[6] if len(parts) == 7 else "")
        elif len(parts) >= 4:                     # 旧 fixture: pid user etime args
            meta[parts[0]] = (parts[1], parts[2], None, None, None,
                              " ".join(parts[3:]))
    out = []
    for r in rows:
        if len(r) < 4:
            continue
        user, elapsed, cpu, pmem, rss, args = meta.get(
            r[1], ("?", "?", None, None, None, r[2]))
        sm, bw = pmon.get(r[1], (None, None))
        out.append({"pid": int(r[1]), "user": user, "command": args,
                    "gpu_mem_mb": _num(r[3]), "gpu_index": uuid_to_idx.get(r[0]),
                    "elapsed": elapsed,
                    "cpu_pct": _num(cpu), "host_mem_pct": _num(pmem),
                    "host_mem_kb": _num(rss),
                    "sm_pct": sm, "mem_bw_pct": bw})
    return out


# ---------- TOP 进程 ----------
def read_top(base="/proc", n=10):
    passwd = {}
    for line in _read_first([base + "/passwd", "/etc/passwd"]).splitlines():
        f = line.split(":")
        if len(f) >= 7:
            passwd[f[2]] = f[0]
    try:
        clk = os.sysconf("SC_CLK_TCK")
    except (ValueError, OSError, AttributeError):
        clk = 100
    try:
        page = os.sysconf("SC_PAGE_SIZE")
    except (ValueError, OSError, AttributeError):
        page = 4096
    uptime = 0.0
    text = _read(base + "/uptime")
    if text:
        uptime = float(text.split()[0])
    procs = []
    try:
        entries = os.listdir(base)                    # 生产 base 即 /proc，pid 目录与其同层
    except (IOError, OSError):
        entries = []
    for name in entries:
        if not name.isdigit():
            continue
        try:
            stat = _read(base + "/" + name + "/stat")
            head, rest = stat.split("(", 1)
            comm, tail = rest[:rest.rindex(")")], rest[rest.rindex(")") + 2:].split()
            utime, stime, starttime = int(tail[11]), int(tail[12]), int(tail[19])
            rss_pages = int(tail[21])
            elapsed = uptime - starttime / float(clk)
            if elapsed <= 0:
                continue
            cpu = ((utime + stime) / float(clk)) * 100.0 / elapsed
            uid = ""
            status = _read(base + "/" + name + "/status")
            for line in status.splitlines():
                if line.startswith("Uid:"):
                    uid = line.split()[1]
                    break
            user = passwd.get(uid, uid or "?")
            cmd = _read(base + "/" + name + "/cmdline").replace("\x00", " ").strip()
            if not cmd:
                cmd = "[" + comm + "]"
            procs.append({"pid": int(head.strip()), "user": user,
                          "cpu": round(cpu, 1),
                          "mem": round(rss_pages * page / 1048576.0, 1),
                          "command": cmd[:120]})
        except (IOError, OSError, IndexError, ValueError):
            continue
    top_cpu = sorted(procs, key=lambda p: -p["cpu"])[:n]
    top_mem = sorted(procs, key=lambda p: -p["mem"])[:n]
    return top_cpu, top_mem


# ---------- 组装 ----------
def collect(base="/proc", interval=0.2, top_n=10):
    errors = []

    def safe(fn, *a, **k):
        try:
            return fn(*a, **k)
        except Exception as e:                      # 单段失败不拖垮整份快照
            errors.append("%s: %s" % (getattr(fn, "__name__", "?"), e))
            return None

    pg, pp, pm = _nvidia_launch(base)      # 先并行点火，与下面的 /proc 读取重叠
    host = safe(read_host, base)
    cpu = safe(read_cpu, base, interval)
    mem = safe(read_mem, base)
    disks = safe(read_disks, base)
    net = safe(read_net, base)
    g_text, a_text, pm_text = (_nvidia_collect(pg), _nvidia_collect(pp),
                               _nvidia_collect(pm))
    gpus = safe(read_gpus, base, g_text)
    gprocs = safe(read_gpu_processes, base, gpus or [], a_text, pm_text)
    top = safe(read_top, base, top_n) or ([], [])
    return {"ts": time.time(), "errors": errors,
            "host": host or {}, "cpu": cpu or {}, "memory": mem or {},
            "disks": disks or [], "gpus": gpus or [], "gpu_processes": gprocs or [],
            "net": net or [], "top_cpu": top[0], "top_mem": top[1]}


def main():
    # 执行参数：sys.argv[1] 为 top_n（由 runner 在载荷尾部追加，见 runner.py）
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    json.dump(collect(top_n=n), sys.stdout)


if __name__ == "__main__":
    main()
