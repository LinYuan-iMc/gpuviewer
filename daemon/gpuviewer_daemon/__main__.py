"""入口：python -m gpuviewer_daemon --config config.toml"""
import argparse
import asyncio
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

import uvicorn

from gpuviewer_daemon.api import make_app
from gpuviewer_daemon.app import Daemon


def setup_logging(log_dir: Path | None = None) -> None:
    """INFO 主日志 + 第三方噪音降级。

    实测 1s 采集 × 多机轮询下，asyncssh 的通道明细与 uvicorn.access 的逐请求
    行合计每秒 ~10 条 INFO，10MB×5 轮转只覆盖约 1 小时——故障回溯窗口为零。
    两者降到 WARNING（错误仍全量保留），业务日志维持 INFO。
    """
    if log_dir is None:
        log_dir = Path("logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(log_dir / "daemon.log", maxBytes=10 * 1024 * 1024,
                                  backupCount=5, encoding="utf-8")
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s",
                        handlers=[handler, logging.StreamHandler()])
    for name in ("asyncssh", "uvicorn.access"):
        logging.getLogger(name).setLevel(logging.WARNING)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.toml")
    args = ap.parse_args()
    setup_logging()
    log = logging.getLogger("gpuviewer")

    async def run():
        daemon = Daemon(args.config)
        await daemon.start()
        ucfg = uvicorn.Config(make_app(daemon), host=daemon.config.daemon.listen_host,
                              port=daemon.config.daemon.listen_port, log_config=None)
        server = uvicorn.Server(ucfg)
        try:
            await server.serve()
        finally:
            await daemon.stop()
        log.info("daemon stopped")

    asyncio.run(run())


if __name__ == "__main__":
    main()
