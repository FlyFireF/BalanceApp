"""应用全局配置：名称、版本、数据/备份/日志目录的解析与创建。

数据目录规则（需求 §35/§36）：
- 不把数据库放进程序安装目录（Windows 下可能没有写权限）；
- 默认使用 %LOCALAPPDATA%\\MoneyManager，始终可写、与程序文件分离，升级不丢数据；
- 允许通过环境变量 MONEY_MANAGER_DATA_DIR 覆盖（测试即用此方式指向临时目录）。
"""

from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "Money Manager"
APP_SLUG = "MoneyManager"  # 目录名不使用空格，避免路径问题
APP_VERSION = "0.2.1"

# 覆盖数据目录的环境变量名
DATA_DIR_ENV_VAR = "MONEY_MANAGER_DATA_DIR"

# 自动备份默认保留天数（可在设置中修改）
DEFAULT_BACKUP_RETENTION_DAYS = 30
BACKUP_RETENTION_KEY = "backup_retention_days"


def get_data_dir() -> Path:
    """数据根目录。

    优先级：
    1. 环境变量 MONEY_MANAGER_DATA_DIR（测试 / 高级用户自定义）
    2. %LOCALAPPDATA%\\MoneyManager（Windows 默认，始终可写）
    """
    override = os.environ.get(DATA_DIR_ENV_VAR)
    if override:
        return Path(override).expanduser()
    local_app_data = os.environ.get("LOCALAPPDATA")
    base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    return base / APP_SLUG


def get_db_path() -> Path:
    """SQLite 数据库文件路径。"""
    return get_data_dir() / "data" / "money_manager.db"


def get_backup_dir() -> Path:
    """自动备份目录。"""
    return get_data_dir() / "backups"


def get_log_dir() -> Path:
    """日志目录。"""
    return get_data_dir() / "logs"


def ensure_directories() -> None:
    """确保数据 / 备份 / 日志目录存在。"""
    for path in (get_db_path().parent, get_backup_dir(), get_log_dir()):
        path.mkdir(parents=True, exist_ok=True)
