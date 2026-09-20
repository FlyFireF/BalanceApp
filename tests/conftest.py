"""pytest 共享夹具：为每个测试创建完全独立的临时 SQLite 数据库。"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from database.database import build_engine
from database.models import (
    Account,
    Base,
    Category,
    CategoryType,
    Channel,
    Transaction,
)
from database.seed import seed_defaults
from services.catalog_service import CatalogService
from services.statistics_service import StatisticsService
from services.transaction_service import TransactionService


@pytest.fixture
def empty_session(tmp_path):
    """只建表、不写默认数据的新数据库会话。"""
    engine = build_engine(tmp_path / "test.db")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def seeded_session(tmp_path):
    """建表并写入默认数据的新数据库会话。"""
    engine = build_engine(tmp_path / "test.db")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as seed_session:
        seed_defaults(seed_session)
        seed_session.commit()
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def seeded_factory(tmp_path):
    """建表 + 默认数据，返回会话工厂（服务层测试用，服务各自开独立会话）。"""
    engine = build_engine(tmp_path / "test.db")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as seed_session:
        seed_defaults(seed_session)
        seed_session.commit()
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    engine.dispose()


@pytest.fixture
def catalog_service(seeded_factory):
    """绑定到临时种子库的基础数据查询服务。"""
    return CatalogService(session_factory=seeded_factory)


@pytest.fixture
def transaction_service(seeded_factory):
    """绑定到临时种子库的交易服务。"""
    return TransactionService(session_factory=seeded_factory)


@pytest.fixture
def statistics_service(seeded_factory):
    """绑定到临时种子库的月度统计服务。"""
    return StatisticsService(session_factory=seeded_factory)


@pytest.fixture
def target_factory(tmp_path):
    """独立的种子数据库（导入目标库），与 seeded_factory 完全分离。"""
    db_dir = tmp_path / "target"
    db_dir.mkdir(parents=True, exist_ok=True)
    engine = build_engine(db_dir / "test.db")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as seed_session:
        seed_defaults(seed_session)
        seed_session.commit()
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    engine.dispose()


@pytest.fixture
def make_transaction(seeded_session: Session):
    """交易工厂：基于种子数据快速创建一笔交易（参数可覆盖）。"""
    channel = seeded_session.scalar(select(Channel).where(Channel.name == "Salary"))
    account = seeded_session.scalar(select(Account).where(Account.name == "Bank"))
    category = seeded_session.scalar(
        select(Category).where(
            Category.name == "Other", Category.type == CategoryType.EXPENSE.value
        )
    )

    def _make(**overrides) -> Transaction:
        params: dict = {
            "type": CategoryType.EXPENSE.value,
            "amount": Decimal("50.00"),
            "date": date(2026, 9, 18),
            "channel_id": channel.id,
            "account_id": account.id,
            "category_id": category.id,
        }
        params.update(overrides)
        transaction = Transaction(**params)
        seeded_session.add(transaction)
        seeded_session.commit()
        return transaction

    return _make
