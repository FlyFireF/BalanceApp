"""自动备份服务（需求 §33-§35/§48）。

策略：
- 每天应用启动时调用 daily_backup()：
  · 当天已存在备份 → 不重复创建（需求 §33）；
  · 否则用 SQLite 官方 backup API 生成一致性快照
    backups/YYYY-MM-DD/money_manager_YYYY-MM-DD.db（需求 §35），
    应用运行中也能得到一致数据；
  · 每次启动都会清理超过保留期限的旧备份（需求 §34）；
- 保留天数存于 Setting 表 backup_retention_days，默认 30（需求 §34），
  可在「设置」中修改；
- 数据库文件缺失时跳过备份并记录日志，不阻塞应用启动；
- 非日期命名的目录/文件（如手动备份目录 manual/）一律保留。
"""

from __future__ import annotations

import logging
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy.orm import sessionmaker

from config import settings
from database import database
from database.models import Setting
from services.exceptions import ValidationError

logger = logging.getLogger(__name__)

_MAX_RETENTION_DAYS = 3650


@dataclass(frozen=True)
class BackupResult:
    """自动备份结果。"""

    backup_file: Path
    removed_backups: list[Path]


class BackupService:
    """自动备份与备份清理。"""

    def __init__(
        self,
        session_factory: sessionmaker | None = None,
        db_path: Path | None = None,
        backup_dir: Path | None = None,
    ) -> None:
        """db_path / backup_dir 默认取 settings；测试可注入临时路径。"""
        self._session_factory = session_factory or database.get_session_factory()
        self._db_path = Path(db_path) if db_path is not None else settings.get_db_path()
        self._backup_dir = (
            Path(backup_dir) if backup_dir is not None else settings.get_backup_dir()
        )

    # ---------- 每日备份（需求 §33）----------

    def daily_backup(self, today: date | None = None) -> BackupResult | None:
        """每日启动备份。当天已备份 → 返回 None；否则创建备份。

        无论是否新建备份，都会清理过期备份（需求 §34）。
        today 参数仅供测试注入，正常运行使用系统日期。
        """
        today = today or date.today()
        removed = self.cleanup_old_backups(today)

        target_dir = self._backup_dir / today.isoformat()
        target_file = target_dir / f"money_manager_{today.isoformat()}.db"
        if target_file.exists():
            logger.info("今天已有备份，跳过：%s", target_file)
            return None
        if not self._db_path.exists():
            logger.warning("数据库文件不存在，跳过备份：%s", self._db_path)
            return None

        target_dir.mkdir(parents=True, exist_ok=True)
        self._copy_database(target_file)
        logger.info("自动备份完成：%s", target_file)
        return BackupResult(backup_file=target_file, removed_backups=removed)

    def _copy_database(self, target: Path) -> None:
        """SQLite 官方 backup API：应用运行中也能得到一致性快照。"""
        source = sqlite3.connect(str(self._db_path))
        try:
            dest = sqlite3.connect(str(target))
            try:
                source.backup(dest)
            finally:
                dest.close()
        finally:
            source.close()

    # ---------- 过期清理（需求 §34）----------

    def cleanup_old_backups(self, today: date | None = None) -> list[Path]:
        """删除超过保留期限的备份目录，返回被删除的目录列表。

        仅清理「日期命名」的目录；其他目录/文件（如 manual）保留。
        """
        today = today or date.today()
        cutoff = today - timedelta(days=self.get_retention_days())
        removed: list[Path] = []
        if not self._backup_dir.exists():
            return removed
        for entry in sorted(self._backup_dir.iterdir()):
            if not entry.is_dir():
                continue
            try:
                backup_date = date.fromisoformat(entry.name)
            except ValueError:
                continue  # 非日期目录不清理
            if backup_date < cutoff:
                try:
                    shutil.rmtree(entry)
                except OSError:
                    logger.warning("删除过期备份失败：%s", entry, exc_info=True)
                    continue
                removed.append(entry)
                logger.info("已删除过期备份：%s", entry)
        return removed

    # ---------- 保留天数（需求 §34/§47）----------

    def get_retention_days(self) -> int:
        """当前保留天数；设置缺失或非法时回退默认 30。"""
        with database.session_scope(self._session_factory) as session:
            setting = session.get(Setting, settings.BACKUP_RETENTION_KEY)
            if setting is None:
                return settings.DEFAULT_BACKUP_RETENTION_DAYS
            try:
                days = int(setting.value)
            except ValueError:
                logger.warning("备份保留天数非法（%r），使用默认值", setting.value)
                return settings.DEFAULT_BACKUP_RETENTION_DAYS
            if days < 1:
                logger.warning("备份保留天数非法（%r），使用默认值", setting.value)
                return settings.DEFAULT_BACKUP_RETENTION_DAYS
            return days

    def set_retention_days(self, days: int) -> None:
        """修改保留天数（1 ~ 3650）。修改后立即生效。"""
        if not isinstance(days, int) or isinstance(days, bool):
            raise ValidationError("保留天数必须是整数")
        if days < 1 or days > _MAX_RETENTION_DAYS:
            raise ValidationError(f"保留天数必须在 1 ~ {_MAX_RETENTION_DAYS} 之间")
        with database.session_scope(self._session_factory) as session:
            setting = session.get(Setting, settings.BACKUP_RETENTION_KEY)
            if setting is None:
                session.add(Setting(key=settings.BACKUP_RETENTION_KEY, value=str(days)))
            else:
                setting.value = str(days)
        logger.info("备份保留天数修改为 %d", days)
