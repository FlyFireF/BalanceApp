"""日志配置：写入 logs/app.log（自动轮转）并输出到控制台。

按需求 §48 记录：应用启动、数据库初始化、导入、导出、自动备份、未处理异常。
不记录敏感数据的完整内容。
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

_configured = False


def setup_logging(log_dir: Path) -> None:
    """初始化根日志器（幂等，重复调用无效）。"""
    global _configured
    if _configured:
        return

    log_dir.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = RotatingFileHandler(
        log_dir / "app.log",
        maxBytes=1_000_000,  # 1 MB 轮转，避免日志无限增长
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(file_handler)
    root.addHandler(console_handler)
    _configured = True
