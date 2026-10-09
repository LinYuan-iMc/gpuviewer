#!/usr/bin/env bash
# 无 systemd 环境兜底：nohup 后台运行守护进程。
#
# 两种位置均可运行：
#   - 仓库内 daemon/deploy/start_nohup.sh：自动定位到仓库根（需本机已建 venv，否则用 python3）
#   - 远端部署目录 ~/gpuviewer/start_nohup.sh：直接在所在目录运行
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ -f "${SCRIPT_DIR}/config.toml" ]; then
    APP_DIR="${SCRIPT_DIR}"                          # 远端部署目录布局
else
    APP_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"     # 仓库布局
fi
cd "${APP_DIR}"

export PYTHONPATH="${APP_DIR}/daemon:${APP_DIR}/shared"

PY="${APP_DIR}/venv/bin/python"
if [ ! -x "${PY}" ]; then
    PY="$(command -v python3)"
    echo "!! 未找到 ${APP_DIR}/venv，回退到 ${PY}（请确认依赖已安装）" >&2
fi

mkdir -p logs data
nohup "${PY}" -m gpuviewer_daemon --config config.toml >> logs/nohup.out 2>&1 &
echo $! > logs/nohup.pid
echo "started pid $! (log: ${APP_DIR}/logs/nohup.out, 停止: kill \$(cat ${APP_DIR}/logs/nohup.pid))"
