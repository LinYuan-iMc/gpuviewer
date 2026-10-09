"""日志降噪：第三方 INFO 噪音降到 WARNING，业务日志不受影响。"""
import logging


def test_third_party_log_noise_silenced(tmp_path):
    from gpuviewer_daemon.__main__ import setup_logging
    setup_logging(tmp_path)
    assert logging.getLogger("asyncssh").level == logging.WARNING
    assert logging.getLogger("uvicorn.access").level == logging.WARNING
    # 业务 logger 未被显式降级（继承 root 的 INFO）
    assert logging.getLogger("gpuviewer").level == logging.NOTSET
