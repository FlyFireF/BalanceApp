"""极简的 Schema 版本迁移机制（需求 §53）。

原则：
- 绝不 drop_all() / 重建数据库，用户数据必须保留；
- 每次数据库结构变更：写一个迁移函数，用 @migration(版本号) 注册；
- run_migrations() 只执行「版本号 > 已记录版本」的迁移。

当前版本：
- v1：初始建表 + 默认数据（Channel / Account / Category / Setting）。
- v2：交易表外键改为「软外键」（可空 + ON DELETE SET NULL）——
  渠道/账户/分类被删除时历史交易不受影响（核心原则：数据库没有硬性外键）。
- v3：渠道新增「每月固定金额」列（默认 0，用户确认的功能）。
- v4：渠道/账户/分类新增「自定义排序」列（默认 0，用户反馈）。
"""

from __future__ import annotations

from typing import Callable

from sqlalchemy import Engine, text
from sqlalchemy.orm import sessionmaker

from database.models import Base
from database.seed import seed_defaults

MigrationFn = Callable[[Engine], None]

_MIGRATIONS: list[tuple[int, MigrationFn]] = []


def migration(version: int) -> Callable[[MigrationFn], MigrationFn]:
    """注册迁移函数的装饰器：@migration(1)。"""

    def register(fn: MigrationFn) -> MigrationFn:
        _MIGRATIONS.append((version, fn))
        return fn

    return register


@migration(1)
def _v1_initial_schema(engine: Engine) -> None:
    """初始 Schema：创建全部表 + 写入默认数据。"""
    Base.metadata.create_all(engine)  # 只建缺失的表，已有数据不受影响
    with sessionmaker(bind=engine, expire_on_commit=False)() as session:
        seed_defaults(session)
        session.commit()


@migration(2)
def _v2_transactions_soft_foreign_keys(engine: Engine) -> None:
    """交易表外键改为「软外键」：可空 + ON DELETE SET NULL。

    SQLite 不支持直接修改列约束，需重建表（数据逐行保留）。
    旧库（v1 硬外键结构）升级后：历史交易原样保留，实体删除不再阻断/级联。
    """
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE transactions_new ("
                "id INTEGER NOT NULL PRIMARY KEY,"
                "type VARCHAR(10) NOT NULL,"
                "amount INTEGER NOT NULL,"
                "date DATE NOT NULL,"
                "channel_id INTEGER REFERENCES channels (id) ON DELETE SET NULL,"
                "account_id INTEGER REFERENCES accounts (id) ON DELETE SET NULL,"
                "category_id INTEGER REFERENCES categories (id) ON DELETE SET NULL,"
                "note VARCHAR(500) NOT NULL,"
                "tags VARCHAR(200) NOT NULL,"
                "created_at DATETIME NOT NULL,"
                "updated_at DATETIME NOT NULL,"
                "CONSTRAINT ck_transactions_type CHECK (type IN ('income', 'expense')),"
                "CONSTRAINT ck_transactions_amount_positive CHECK (amount > 0)"
                ")"
            )
        )
        conn.execute(
            text(
                "INSERT INTO transactions_new (id, type, amount, date, channel_id, account_id,"
                " category_id, note, tags, created_at, updated_at)"
                " SELECT id, type, amount, date, channel_id, account_id, category_id,"
                " note, tags, created_at, updated_at FROM transactions"
            )
        )
        conn.execute(text("DROP TABLE transactions"))
        conn.execute(text("ALTER TABLE transactions_new RENAME TO transactions"))
        conn.execute(text("CREATE INDEX ix_transactions_date ON transactions (date)"))
        conn.execute(
            text("CREATE INDEX ix_transactions_channel_id ON transactions (channel_id)")
        )
        conn.execute(
            text("CREATE INDEX ix_transactions_account_id ON transactions (account_id)")
        )
        conn.execute(
            text("CREATE INDEX ix_transactions_category_id ON transactions (category_id)")
        )


@migration(3)
def _v3_channel_monthly_amount(engine: Engine) -> None:
    """渠道新增「每月固定金额」列（整数分，默认 0）。

    幂等：全新安装时 v1 的 create_all 已用新模型建出该列，此时跳过；
    旧库（v2 时代结构）升级时才真正执行 ALTER。
    """
    with engine.connect() as conn:
        columns = [row[1] for row in conn.execute(text("PRAGMA table_info(channels)"))]
    if "monthly_amount" in columns:
        return
    with engine.begin() as conn:
        conn.execute(
            text(
                "ALTER TABLE channels ADD COLUMN monthly_amount INTEGER NOT NULL DEFAULT 0"
            )
        )


@migration(4)
def _v4_entity_sort_order(engine: Engine) -> None:
    """渠道/账户/分类新增「自定义排序」列（默认 0）。幂等：全新安装时
    v1 的 create_all 已含该列则跳过；旧库升级时才真正执行 ALTER。"""
    for table in ("channels", "accounts", "categories"):
        with engine.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM sqlite_master WHERE type='table' AND name=:name"),
                {"name": table},
            ).scalar()
            if not exists:
                continue  # 表不存在（异常状态的旧库）：跳过
            columns = [row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))]
        if "sort_order" in columns:
            continue
        with engine.begin() as conn:
            conn.execute(
                text(f"ALTER TABLE {table} ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0")
            )


def run_migrations(engine: Engine) -> None:
    """按版本号顺序执行尚未应用的迁移。"""
    _ensure_version_table(engine)
    current = _current_version(engine)
    for version, fn in sorted(_MIGRATIONS):
        if version > current:
            fn(engine)
            _set_version(engine, version)


def _ensure_version_table(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
        )


def _current_version(engine: Engine) -> int:
    with engine.connect() as conn:
        result = conn.execute(
            text("SELECT COALESCE(MAX(version), 0) FROM schema_version")
        )
        return int(result.scalar())


def _set_version(engine: Engine, version: int) -> None:
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO schema_version (version) VALUES (:version)"),
            {"version": version},
        )
