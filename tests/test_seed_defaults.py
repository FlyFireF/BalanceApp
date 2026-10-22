"""测试默认数据（种子数据）：正确写入、幂等、不干扰用户已有修改（需求 §43/§26）。"""

from __future__ import annotations

from sqlalchemy import select

from database.models import Account, Category, CategoryType, Channel, Setting
from database.seed import (
    DEFAULT_ACCOUNTS,
    DEFAULT_CHANNELS,
    DEFAULT_EXPENSE_CATEGORIES,
    DEFAULT_INCOME_CATEGORIES,
    seed_defaults,
)


def test_default_channels_created(seeded_session):
    channels = seeded_session.scalars(select(Channel)).all()
    assert {c.name for c in channels} == set(DEFAULT_CHANNELS)
    assert all(c.is_active for c in channels)


def test_default_accounts_created(seeded_session):
    accounts = seeded_session.scalars(select(Account)).all()
    assert {a.name for a in accounts} == set(DEFAULT_ACCOUNTS)
    assert all(a.is_active for a in accounts)
    assert all(a.initial_balance == 0 for a in accounts)


def test_default_income_categories_created(seeded_session):
    names = {
        c.name
        for c in seeded_session.scalars(select(Category))
        if c.type == CategoryType.INCOME.value
    }
    assert names == set(DEFAULT_INCOME_CATEGORIES)


def test_default_expense_categories_created(seeded_session):
    names = {
        c.name
        for c in seeded_session.scalars(select(Category))
        if c.type == CategoryType.EXPENSE.value
    }
    assert names == set(DEFAULT_EXPENSE_CATEGORIES)


def test_default_categories_keep_declared_order(seeded_session):
    """默认分类按声明顺序写入 sort_order：列表第一项即记账页默认选中项。"""
    for category_type, expected in (
        (CategoryType.EXPENSE.value, DEFAULT_EXPENSE_CATEGORIES),
        (CategoryType.INCOME.value, DEFAULT_INCOME_CATEGORIES),
    ):
        names = seeded_session.scalars(
            select(Category.name)
            .where(Category.type == category_type)
            .order_by(Category.sort_order)
        ).all()
        assert names == expected


def test_other_category_exists_for_both_types(seeded_session):
    """收入与支出必须各有一个独立的 Other 分类（逻辑隔离）。"""
    income_other = seeded_session.scalar(
        select(Category).where(
            Category.name == "Other", Category.type == CategoryType.INCOME.value
        )
    )
    expense_other = seeded_session.scalar(
        select(Category).where(
            Category.name == "Other", Category.type == CategoryType.EXPENSE.value
        )
    )
    assert income_other is not None
    assert expense_other is not None
    assert income_other.id != expense_other.id


def test_seed_is_idempotent(seeded_session):
    """重复执行种子写入不应产生重复数据。"""
    channel_names = {c.name for c in seeded_session.scalars(select(Channel))}
    account_names = {a.name for a in seeded_session.scalars(select(Account))}
    category_count = len(seeded_session.scalars(select(Category)).all())

    seed_defaults(seeded_session)
    seeded_session.commit()

    assert {c.name for c in seeded_session.scalars(select(Channel))} == channel_names
    assert {a.name for a in seeded_session.scalars(select(Account))} == account_names
    assert len(seeded_session.scalars(select(Category)).all()) == category_count


def test_seed_does_not_reactivate_deactivated_channel(seeded_session):
    """用户停用的默认渠道不应被种子数据重新激活。"""
    salary = seeded_session.scalar(select(Channel).where(Channel.name == "Salary"))
    salary.is_active = False
    seeded_session.commit()

    seed_defaults(seeded_session)
    seeded_session.commit()

    salary = seeded_session.scalar(select(Channel).where(Channel.name == "Salary"))
    assert salary.is_active is False


def test_default_settings_seeded(seeded_session):
    retention = seeded_session.get(Setting, "backup_retention_days")
    assert retention is not None
    assert retention.value == "30"
    theme = seeded_session.get(Setting, "theme")
    assert theme is not None
    assert theme.value == "system"  # 默认跟随系统
