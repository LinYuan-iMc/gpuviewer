# scripts

## 实机 fixtures 采集（黄金测试用）

从真实 GPU 服务器抓取只读系统指标（/proc 样本 + nvidia-smi 输出 + /etc/passwd
用户名列表），存入 `tests/fixtures/real/<host>/proc/`，供
`tests/daemon/test_real_golden.py` 校验探针解析；未采集时该测试自动 skip。

两个入口，**优先用 py 版**（Windows Git Bash 无 sshpass，sh 版交互输密码不可行）：

```bash
# py 版：非交互，密码从环境变量读（绝不写入命令行或任何提交文件）
GPUVIEWER_SSH_PASS='...' python scripts/capture_fixtures.py --host 192.168.1.10 --user user1

# sh 版：Linux/有 sshpass 环境可用，密码交互输入
bash scripts/capture_fixtures.sh 192.168.1.11 user2
```

安全约定：采集脚本只从环境变量 `GPUVIEWER_SSH_PASS`（py 版）或交互输入
（sh 版）取得密码；fixtures 内容为只读系统指标，不含凭据，可入库。
