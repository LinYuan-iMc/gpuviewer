#!/usr/bin/env bash
# 远端安装脚本：在目标服务器上执行（无 root、无交互输入）。
#
# 由 daemon/deploy/deploy.sh 同步到服务器 ~/gpuviewer/deploy_remote.sh 后调用，
# 也可被非交互部署器（如 asyncssh）直接上传到部署目录执行。
#
# 预期部署目录布局（与 gpuviewer.service 的路径保持一致）：
#   ~/gpuviewer/
#     daemon/gpuviewer_daemon/     守护进程包
#     daemon/requirements.txt
#     shared/gpuviewer_shared/     共享 schema 包
#     gpuviewer.service            systemd 用户单元（拷到 ~/.config/systemd/user/）
#     start_nohup.sh               无 systemd 兜底
#     deploy_remote.sh             本脚本
#     run.sh                       本脚本生成的启动包装器（service/nohup 共用）
#     venv/  config.toml  data/  logs/   （运行期生成；venv 缺失时降级 --user 安装）
#
# 用法（在部署目录内）:
#   bash deploy_remote.sh                # venv + 依赖 + 配置 + systemd 用户服务
#   bash deploy_remote.sh --skip-service # 只更新代码与依赖，不动 systemd（重启见 README「升级」）
set -euo pipefail
APP_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "${APP_DIR}"

INSTALL_SERVICE=1
if [ "${1:-}" = "--skip-service" ]; then
    INSTALL_SERVICE=0
fi

echo "==> 预检远端 Python (>=3.9)"
python3 -c 'import sys; assert sys.version_info >= (3, 9), sys.version; print("    python", sys.version.split()[0])'

echo "==> 建立虚拟环境并安装依赖"
USE_VENV=1
if [ ! -x venv/bin/python ]; then
    if ! python3 -m venv venv || [ ! -x venv/bin/python ]; then
        echo "!! python3 -m venv 失败（服务器无 python3-venv/ensurepip，已实测 Ubuntu 22.04 最小安装）" >&2
        echo "!! 清理残缺 venv 并降级为 get-pip 引导的 --user 安装" >&2
        rm -rf venv                      # 残缺 venv 会骗过 run.sh 的解释器探测，必须清掉
        USE_VENV=0
    fi
fi
if [ "${USE_VENV}" = "1" ]; then
    venv/bin/pip install -q -r daemon/requirements.txt
else
    if ! python3 -m pip --version >/dev/null 2>&1; then
        echo "==> get-pip 引导用户级 pip（无 root，装到 ~/.local）"
        curl -sSL https://bootstrap.pypa.io/get-pip.py | python3 - --user
    fi
    python3 -m pip install --user -r daemon/requirements.txt
fi

echo "==> 生成启动包装器 run.sh（venv 优先，缺失时回退 python3；重复生成幂等）"
cat > run.sh <<'EOF'
#!/usr/bin/env bash
cd "$HOME/gpuviewer"
if [ -x venv/bin/python ]; then PY=venv/bin/python; else PY=python3; fi
export PYTHONPATH="$HOME/gpuviewer/daemon:$HOME/gpuviewer/shared"
mkdir -p logs data
exec "$PY" -m gpuviewer_daemon --config config.toml
EOF
chmod +x run.sh

echo "==> 生成配置 config.toml（已存在则保留，凭据不回传本地）"
umask 077                            # 创建即 600，消除 chmod 前的他人可读窗口
if [ ! -f config.toml ]; then
    # 随机 token 只落在远端文件里；更多被监控机后续经客户端/CRUD API 注册
    TOKEN="$(head -c 24 /dev/urandom | base64 | tr -d '/+=')"
    NAME="$(hostname)"
    cat > config.toml <<EOF
[daemon]
listen_host = "0.0.0.0"
listen_port = 7421
token = "${TOKEN}"
db_path = "data/gpuviewer.db"
interval_s = 5.0
probe_timeout_s = 10.0
accept_host_keys = true
top_n = 10

[[servers]]
id = "local"
name = "${NAME}"
transport = "local"
enabled = true
EOF
    chmod 600 config.toml
    echo "    已生成 config.toml（随机 token 已写入，本机注册为被监控机）"
    echo "    查看随机 token:  grep '^token' ~/gpuviewer/config.toml"
else
    echo "    config.toml 已存在，保留不改"
fi

if [ "${INSTALL_SERVICE}" = "1" ]; then
    echo "==> 安装 systemd 用户服务"
    # service 用仓库 daemon/deploy/gpuviewer.service；repo 布局优先，deploy.sh
    # 同步的顶层副本（~/gpuviewer/gpuviewer.service）兜底，两处内容一致
    SERVICE_SRC="${APP_DIR}/daemon/deploy/gpuviewer.service"
    if [ ! -f "${SERVICE_SRC}" ]; then
        SERVICE_SRC="${APP_DIR}/gpuviewer.service"
    fi
    # 非登录 shell 里 systemctl --user 需要 XDG_RUNTIME_DIR
    export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
    if mkdir -p "${HOME}/.config/systemd/user" \
       && cp "${SERVICE_SRC}" "${HOME}/.config/systemd/user/gpuviewer.service" \
       && systemctl --user daemon-reload \
       && systemctl --user enable gpuviewer.service \
       && systemctl --user restart gpuviewer.service; then
        systemctl --user --no-pager --lines=5 status gpuviewer.service || true
    else
        echo "!! systemd 用户服务安装失败（无 systemd 或用户总线不可用）。" >&2
        echo "!! 兜底方案: bash ${APP_DIR}/start_nohup.sh" >&2
        exit 3
    fi
fi

echo "==> 远端安装完成"
