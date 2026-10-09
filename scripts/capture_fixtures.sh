#!/usr/bin/env bash
# 用法: scripts/capture_fixtures.sh 192.168.1.11 user2
# Linux/有 sshpass 环境可用；Windows Git Bash 无 sshpass，请优先用
# scripts/capture_fixtures.py（GPUVIEWER_SSH_PASS 环境变量传密码，非交互）。
# 采集物为只读系统指标文本（含 /etc/passwd 用户名列表），不含任何凭据。
set -euo pipefail
cd "$(dirname "$0")/.."
HOST="$1"; USER_="${2:-$USER}"; OUT="tests/fixtures/real/$(echo "$HOST" | tr . _)"
mkdir -p "$OUT"
ssh "$USER_@$HOST" 'cat /proc/stat; echo ---; cat /proc/meminfo; echo ---; cat /proc/mounts; echo ---; cat /proc/net/dev; echo ---; cat /proc/loadavg; echo ---; cat /proc/uptime; echo ---; grep PRETTY /etc/os-release; echo ---; cat /etc/passwd; echo ---; nvidia-smi --query-gpu=index,name,uuid,utilization.gpu,utilization.memory,memory.used,memory.total,temperature.gpu,power.draw,power.limit,fan.speed --format=csv,noheader,nounits; echo ---; nvidia-smi --query-compute-apps=gpu_uuid,pid,process_name,used_memory --format=csv,noheader,nounits || true' > "$OUT/raw.txt"
python - "$OUT/raw.txt" <<'EOF'
import pathlib
import sys

raw = pathlib.Path(sys.argv[1]).read_text()
parts = [p.strip() for p in raw.split("---")]
names = ["stat", "meminfo", "mounts", "dev", "loadavg", "uptime", "os-release",
         "passwd", "nvidia-smi-gpu.txt", "nvidia-smi-compute-apps.txt"]
if len(parts) < len(names):
    raise SystemExit("远端输出分段数不足（SSH 会话异常？）")
out = pathlib.Path(sys.argv[1]).parent
proc = out / "proc"
proc.mkdir(exist_ok=True)
for name, content in zip(names, parts):
    target = proc / "net" / "dev" if name == "dev" else proc / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content + "\n")
EOF
PIDS=$(awk -F', *' 'NF>=4 && $2 ~ /^[0-9]+$/ {print $2}' "$OUT/proc/nvidia-smi-compute-apps.txt" | paste -sd, -)
if [ -n "$PIDS" ]; then
    ssh "$USER_@$HOST" "ps -o pid=,user=,etime=,args= -p $PIDS" > "$OUT/proc/ps-gpu.txt"
else
    : > "$OUT/proc/ps-gpu.txt"
fi
rm -f "$OUT/raw.txt"
echo "fixtures saved to $OUT/proc"
