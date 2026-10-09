#!/usr/bin/env bash
# 一键部署守护进程到 GPU 服务器（无 root，用户级 systemd）。
#
# 用法（在仓库根执行）:
#   DEPLOY_HOST=192.168.1.10 DEPLOY_USER=user1 bash daemon/deploy/deploy.sh
# 或先创建 daemon/deploy/deploy.env（格式见下，勿入库）再直接运行:
#   bash daemon/deploy/deploy.sh
#
# 可选环境变量:
#   DEPLOY_HOST   服务器 IP（必填，或写 deploy.env）
#   DEPLOY_USER   服务器用户（必填，或写 deploy.env）
#   REMOTE_DIR    家目录下的部署目录名，默认 gpuviewer
#                 注意: 非 gpuviewer 时需同步修改 daemon/deploy/gpuviewer.service 里的 %h/gpuviewer
#   DEPLOY_PORT   ssh 端口，默认 22
#   DRY_RUN=1     只打印将执行的命令，不实际连接
#
# deploy.env 示例（KEY=VALUE 每行一条，已导出的环境变量优先于文件）:
#   DEPLOY_HOST=192.168.1.10
#   DEPLOY_USER=user1
#
# 代码同步是双路径：本机有 rsync 用 rsync（增量 + --delete 清理陈旧文件）；
# 没有（如 Windows Git Bash）则降级为 tar 打包走 ssh（覆盖式，不删除远端陈旧文件）。
# 远端安装步骤（venv/pip/config/systemd）在 scripts/deploy_remote.sh 中，
# 本脚本会把它一并同步到服务器执行，也可供非交互部署器单独调用。
set -euo pipefail
cd "$(dirname "$0")/../.."          # 仓库根

ENV_FILE="daemon/deploy/deploy.env"

# ---------- 参数：环境变量优先，deploy.env 兜底 ----------
if [ -f "${ENV_FILE}" ]; then
    _h="${DEPLOY_HOST:-}"; _u="${DEPLOY_USER:-}"; _d="${REMOTE_DIR:-}"
    # shellcheck disable=SC1090
    . "${ENV_FILE}"
    DEPLOY_HOST="${_h:-${DEPLOY_HOST:-}}"
    DEPLOY_USER="${_u:-${DEPLOY_USER:-}}"
    REMOTE_DIR="${_d:-${REMOTE_DIR:-}}"
fi
DEPLOY_HOST="${DEPLOY_HOST:-}"
DEPLOY_USER="${DEPLOY_USER:-}"
REMOTE_DIR="${REMOTE_DIR:-gpuviewer}"
DEPLOY_PORT="${DEPLOY_PORT:-22}"

if [ -z "${DEPLOY_HOST}" ] || [ -z "${DEPLOY_USER}" ]; then
    cat >&2 <<EOF
用法: DEPLOY_HOST=<服务器IP> DEPLOY_USER=<用户名> [REMOTE_DIR=gpuviewer] [DEPLOY_PORT=22] [DRY_RUN=1] \\
        bash daemon/deploy/deploy.sh
或创建 ${ENV_FILE}（DEPLOY_HOST=... / DEPLOY_USER=...，勿入库）后直接运行。
示例: DEPLOY_HOST=192.168.1.10 DEPLOY_USER=user1 bash daemon/deploy/deploy.sh
EOF
    exit 2
fi

TARGET="${DEPLOY_USER}@${DEPLOY_HOST}"
SSH_CMD=(ssh -p "${DEPLOY_PORT}" "${TARGET}")

run() {                              # 本地命令的 DRY_RUN 包装
    if [ "${DRY_RUN:-0}" = "1" ]; then printf '[dry-run] %s\n' "$*"; else "$@"; fi
}
run_sh() {                           # 远端命令的 DRY_RUN 包装（回显与真实 ssh 命令一致，含 -p）
    if [ "${DRY_RUN:-0}" = "1" ]; then
        printf '[dry-run] ssh -p %s %s %s\n' "${DEPLOY_PORT}" "${TARGET}" "$1"
    else
        "${SSH_CMD[@]}" "$1"
    fi
}
REMOTE_CMD=""                       # sync_tar 的远端解包命令，调用前赋值
sync_tar() {                        # tar over ssh 管道；DRY_RUN 完整回显整条管道
    if [ "${DRY_RUN:-0}" = "1" ]; then
        printf '[dry-run] tar czf -'
        printf ' %q' "$@"
        printf ' | ssh -p %s %s %s\n' "${DEPLOY_PORT}" "${TARGET}" "${REMOTE_CMD}"
    else
        tar czf - "$@" | "${SSH_CMD[@]}" "${REMOTE_CMD}"
    fi
}

echo "==> 目标: ${TARGET}:${REMOTE_DIR} (DRY_RUN=${DRY_RUN:-0})"

echo "==> 预检远端 Python (>=3.9)"
run_sh 'python3 -c "import sys; assert sys.version_info >= (3, 9), sys.version; print(sys.version)"'

echo "==> 同步代码到 ~/${REMOTE_DIR}/"
if command -v rsync >/dev/null 2>&1; then
    RSYNC=(rsync -a --delete --exclude='__pycache__')
    # --rsync-path 先建目录再传，远端无需预建
    run "${RSYNC[@]}" --rsync-path "mkdir -p '${REMOTE_DIR}/daemon' '${REMOTE_DIR}/shared' && rsync" \
        daemon/gpuviewer_daemon daemon/requirements.txt "${TARGET}:${REMOTE_DIR}/daemon/"
    run "${RSYNC[@]}" --rsync-path "mkdir -p '${REMOTE_DIR}/shared' && rsync" \
        shared/gpuviewer_shared "${TARGET}:${REMOTE_DIR}/shared/"
    run "${RSYNC[@]}" --rsync-path "mkdir -p '${REMOTE_DIR}' && rsync" \
        daemon/deploy/gpuviewer.service daemon/deploy/start_nohup.sh \
        scripts/deploy_remote.sh "${TARGET}:${REMOTE_DIR}/"
else
    echo "    本机无 rsync，降级为 tar over ssh（覆盖式同步，不删除远端陈旧文件）"
    run_sh "mkdir -p '${REMOTE_DIR}/daemon' '${REMOTE_DIR}/shared'"
    # 打包侧 -C 剥掉本地目录前缀，远端解包 -C 落位到目标布局，避免路径翻倍叠加
    REMOTE_CMD="tar xzf - -C '${REMOTE_DIR}/daemon'"
    sync_tar --exclude='__pycache__' -C daemon gpuviewer_daemon requirements.txt
    REMOTE_CMD="tar xzf - -C '${REMOTE_DIR}/shared'"
    sync_tar --exclude='__pycache__' -C shared gpuviewer_shared
    REMOTE_CMD="tar xzf - -C '${REMOTE_DIR}'"
    sync_tar -C daemon/deploy gpuviewer.service start_nohup.sh -C "${PWD}/scripts" deploy_remote.sh
fi

echo "==> 远端安装（venv / 依赖 / config.toml / systemd 用户服务）"
run_sh "cd '${REMOTE_DIR}' && bash deploy_remote.sh"

echo "==> 完成。"
echo "    如需退出 SSH 后服务仍保持运行，请管理员执行一次（无 root 无法自助）:"
echo "      sudo loginctl enable-linger ${DEPLOY_USER}"
echo "    状态: systemctl --user status gpuviewer"
echo "    日志: journalctl --user -u gpuviewer -f"
echo "    客户端默认地址: http://${DEPLOY_HOST}:7421（Token 见服务器上 ${REMOTE_DIR}/config.toml）"
