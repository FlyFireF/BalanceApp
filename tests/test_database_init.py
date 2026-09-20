"""测试数据库初始化与极简迁移机制（需求 §43 数据库初始化 / §53 迁移）。"""

from __future__ import annotations

from sqlalchemy import inspect, select
from sqlalchemy.orm import sessionmaker

from config import settings
from database.database import build_engine
from database.migrations import _current_version, run_migrations
from database.models import Channel


def test_migrations_create_all_tables(tmp_path):
    engine = build_engine(tmp_path / "test.db")
    run_migrations(engine)
    tables = set(inspect(engine).get_table_names())
    assert {"channels", "accounts", "categories", "transactions", "settings"} <= tables
    assert "schema_version" in tables
    engine.dispose()


def test_migrations_record_schema_version(tmp_path):
    engine = build_engine(tmp_path / "test.db")
    run_migrations(engine)
    assert _current_version(engine) >= 1
    engine.dispose()


def test_run_migrations_twice_preserves_user_data(tmp_path):
    """重复初始化绝不 drop_all：用户数据必须保留、默认数据不重复。"""
    engine = build_engine(tmp_path / "test.db")
    run_migrations(engine)

    with sessionmaker(bind=engine, expire_on_commit=False)() as session:
        session.add(Channel(name="我的自定义渠道"))
        session.commit()

    run_migrations(engine)

    with sessionmaker(bind=engine, expire_on_commit=False)() as session:
        names = [c.name for c in session.scalars(select(Channel))]
        assert "我的自定义渠道" in names
        assert names.count("Salary") == 1  # 默认数据没有重复
    engine.dispose()


def test_init_db_uses_data_dir_env_var(tmp_path, monkeypatch):
    """init_db 使用环境变量指定的数据目录（可覆盖默认 %LOCALAPPDATA% 路径）。"""
    import database.database as db

    monkeypatch.setenv(settings.DATA_DIR_ENV_VAR, str(tmp_path))
    db._engine = None
    db._session_factory = None
    try:
        db.init_db()
        assert (tmp_path / "data" / "money_manager.db").exists()
    finally:
        if db._engine is not None:
            db._engine.dispose()
        db._engine = None
        db._session_factory = None


def test_migration_v2_softens_foreign_keys_preserving_data(tmp_path):
    """v1 旧结构（硬外键）升级到 v2：历史数据逐行保留、外键变软（SET NULL）。

    模拟真实升级路径：schema_version 已记录为 1（v1 时代已初始化过），
    因此 run_migrations 只执行 v2（重建交易表）与 v3（渠道加列）。
    """
    from sqlalchemy import create_engine, text

    # 直接建引擎（不开 FK pragma），模拟 v1 时代的旧表结构
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE schema_version (version INTEGER NOT NULL)"))
        conn.execute(text("INSERT INTO schema_version (version) VALUES (1)"))
        conn.execute(
            text(
                "CREATE TABLE channels ("
                "id INTEGER NOT NULL, name VARCHAR(50) NOT NULL UNIQUE,"
                "description VARCHAR(200) NOT NULL, is_active BOOLEAN NOT NULL,"
                "created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL,"
                "PRIMARY KEY (id))"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE transactions ("
                "id INTEGER NOT NULL, type VARCHAR(10) NOT NULL, amount INTEGER NOT NULL,"
                "date DATE NOT NULL, channel_id INTEGER NOT NULL, account_id INTEGER NOT NULL,"
                "category_id INTEGER NOT NULL, note VARCHAR(500) NOT NULL,"
                "tags VARCHAR(200) NOT NULL,"
                "created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL,"
                "PRIMARY KEY (id),"
                "CONSTRAINT ck_transactions_type CHECK (type IN ('income', 'expense')),"
                "CONSTRAINT ck_transactions_amount_positive CHECK (amount > 0),"
                "FOREIGN KEY(channel_id) REFERENCES channels (id),"
                "FOREIGN KEY(account_id) REFERENCES accounts (id),"
                "FOREIGN KEY(category_id) REFERENCES categories (id))"
            )
        )
        conn.execute(
            text(
                "INSERT INTO channels (id, name, description, is_active, created_at, updated_at)"
                " VALUES (1, 'Salary', '', 1, '2026-09-18 00:00:00', '2026-09-18 00:00:00')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO transactions (id, type, amount, date, channel_id, account_id,"
                " category_id, note, tags, created_at, updated_at)"
                " VALUES (1, 'expense', 5000, '2026-09-18', 1, 1, 1, '旧数据', '',"
                " '2026-09-18 00:00:00', '2026-09-18 00:00:00')"
            )
        )

    run_migrations(engine)

    with engine.connect() as conn:
        # 数据逐行保留
        row = conn.execute(
            text("SELECT id, type, amount, note, channel_id FROM transactions")
        ).one()
        assert row == (1, "expense", 5000, "旧数据", 1)
        # 外键已软化为 SET NULL
        fks = conn.execute(text("PRAGMA foreign_key_list(transactions)")).fetchall()
        assert fks, "应有外键定义"
        assert all(fk[6] == "SET NULL" for fk in fks)  # on_delete 列
        # v3 为旧库补上渠道的每月固定金额列
        columns = [row[1] for row in conn.execute(text("PRAGMA table_info(channels)"))]
        assert "monthly_amount" in columns
        assert conn.execute(
            text("SELECT MAX(version) FROM schema_version")
        ).scalar() == 3
    engine.dispose()
