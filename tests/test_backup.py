"""测试自动备份（需求 §33-§35/§34/§47）。

today 参数注入使日期相关断言完全确定。
"""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pytest

from database.models import Setting
from helpers import seed_official_scenario
from services.backup_service import BackupService
from services.exceptions import ValidationError

TODAY = date(2026, 9, 18)


def _make_service(seeded_factory, tmp_path):
    """备份服务：数据库路径与 seeded_factory 夹具一致，备份目录独立。"""
    return BackupService(
        session_factory=seeded_factory,
        db_path=tmp_path / "test.db",
        backup_dir=tmp_path / "backups",
    )


def _backup_file(backup_dir: Path, day: date) -> Path:
    return backup_dir / day.isoformat() / f"money_manager_{day.isoformat()}.db"


def _transaction_count(path: Path) -> int:
    conn = sqlite3.connect(str(path))
    try:
        return conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    finally:
        conn.close()


# ---------- 每日备份（需求 §33）----------

def test_daily_backup_creates_consistent_copy(seeded_factory, transaction_service, tmp_path):
    """备份文件是源库的一致性快照。"""
    seed_official_scenario(seeded_factory, transaction_service)
    service = _make_service(seeded_factory, tmp_path)

    result = service.daily_backup(today=TODAY)

    assert result is not None
    target = _backup_file(tmp_path / "backups", TODAY)
    assert result.backup_file == target
    assert target.exists()
    assert _transaction_count(target) == 4  # 与源库一致


def test_daily_backup_once_per_day(seeded_factory, tmp_path):
    """需求 §33：当天已备份 → 不重复创建。"""
    service = _make_service(seeded_factory, tmp_path)
    assert service.daily_backup(today=TODAY) is not None
    assert service.daily_backup(today=TODAY) is None

    backup_dir = tmp_path / "backups" / TODAY.isoformat()
    assert len(list(backup_dir.iterdir())) == 1


def test_daily_backup_different_days(seeded_factory, tmp_path):
    service = _make_service(seeded_factory, tmp_path)
    assert service.daily_backup(today=TODAY) is not None
    assert service.daily_backup(today=TODAY + timedelta(days=1)) is not None
    assert _backup_file(tmp_path / "backups", TODAY).exists()
    assert _backup_file(tmp_path / "backups", TODAY + timedelta(days=1)).exists()


def test_daily_backup_skips_when_db_missing(seeded_factory, tmp_path):
    service = BackupService(
        session_factory=seeded_factory,
        db_path=tmp_path / "no_such.db",
        backup_dir=tmp_path / "backups",
    )
    assert service.daily_backup(today=TODAY) is None
    assert not (tmp_path / "backups").exists()


# ---------- 过期清理（需求 §34）----------

def test_cleanup_removes_expired_keeps_recent(seeded_factory, tmp_path):
    service = _make_service(seeded_factory, tmp_path)
    backup_dir = tmp_path / "backups"
    # 直接构造历史备份目录（用 daily_backup 造数会在其内部触发清理，干扰断言）
    for days_ago in (40, 20, 10, 5):
        target = _backup_file(backup_dir, TODAY - timedelta(days=days_ago))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("x", encoding="utf-8")

    # 手动备份目录与非日期文件必须保留
    (backup_dir / "manual").mkdir(parents=True, exist_ok=True)
    (backup_dir / "manual" / "keep.db").write_text("x", encoding="utf-8")
    (backup_dir / "readme.txt").write_text("x", encoding="utf-8")

    removed = service.cleanup_old_backups(today=TODAY)

    assert {p.name for p in removed} == {(TODAY - timedelta(days=40)).isoformat()}
    assert not _backup_file(backup_dir, TODAY - timedelta(days=40)).exists()
    for days_ago in (20, 10, 5):
        assert _backup_file(backup_dir, TODAY - timedelta(days=days_ago)).exists()
    assert (backup_dir / "manual" / "keep.db").exists()
    assert (backup_dir / "readme.txt").exists()


def test_cleanup_respects_custom_retention(seeded_factory, tmp_path):
    service = _make_service(seeded_factory, tmp_path)
    for days_ago in (10, 5):
        service.daily_backup(today=TODAY - timedelta(days=days_ago))

    service.set_retention_days(7)
    removed = service.cleanup_old_backups(today=TODAY)

    assert {p.name for p in removed} == {(TODAY - timedelta(days=10)).isoformat()}
    assert _backup_file(tmp_path / "backups", TODAY - timedelta(days=5)).exists()


# ---------- 保留天数（需求 §34/§47）----------

def test_retention_days_default_and_set(seeded_factory, tmp_path):
    service = _make_service(seeded_factory, tmp_path)
    assert service.get_retention_days() == 30  # 默认值

    service.set_retention_days(60)
    assert service.get_retention_days() == 60

    service.set_retention_days(7)
    assert service.get_retention_days() == 7


def test_retention_days_invalid_rejected(seeded_factory, tmp_path):
    service = _make_service(seeded_factory, tmp_path)
    for bad in (0, -5, 4000, 3.5, "30", True):
        with pytest.raises(ValidationError):
            service.set_retention_days(bad)
    assert service.get_retention_days() == 30  # 未被修改


def test_retention_days_corrupted_value_falls_back(seeded_factory, tmp_path):
    with seeded_factory() as session:
        session.get(Setting, "backup_retention_days").value = "abc"
        session.commit()
    service = _make_service(seeded_factory, tmp_path)
    assert service.get_retention_days() == 30
