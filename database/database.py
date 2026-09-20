"""数据库引擎、会话工厂与初始化入口。"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from config import settings

logger = logging.getLogger(__name__)

# 模块级缓存：引擎与会话工厂只创建一次。
# 路径在首次使用时才解析，因此测试可通过环境变量 MONEY_MANAGER_DATA_DIR 指向临时目录。
_engine: Engine | None = None
_session_factory: sessionmaker | None = None


def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:
    """SQLite 默认不开启外键约束，必须通过 PRAGMA 手动开启。"""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def build_engine(db_path: str | Path) -> Engine:
    """根据路径创建 SQLite 引擎（并开启外键约束）。测试也使用此函数。"""
    engine = create_engine(
        f"sqlite:///{Path(db_path)}",
        connect_args={"check_same_thread": False},
    )
    event.listen(engine, "connect", _enable_foreign_keys)
    return engine


def get_engine() -> Engine:
    """获取全局引擎（首次调用时按 settings 路径创建）。"""
    global _engine
    if _engine is None:
        _engine = build_engine(settings.get_db_path())
    return _engine


def get_session_factory() -> sessionmaker:
    """获取全局会话工厂。"""
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(bind=get_engine(), expire_on_commit=False)
    return _session_factory


@contextmanager
def session_scope(session_factory: sessionmaker | None = None) -> Iterator[Session]:
    """事务作用域：正常提交、异常回滚、最终关闭。服务层统一使用。

    可通过 session_factory 注入自定义会话工厂（测试用）；默认使用全局工厂。
    """
    factory = session_factory or get_session_factory()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    """初始化数据库：建缺失的表、写入默认数据、应用未执行的 Schema 迁移。

    绝不 drop_all()：已存在的用户数据不受影响（需求 §53）。
    """
    from database.migrations import run_migrations

    # 确保数据目录存在（目录被手动删除时也能自愈，避免启动失败）
    settings.ensure_directories()
    run_migrations(get_engine())
    logger.info("数据库初始化完成：%s", settings.get_db_path())
