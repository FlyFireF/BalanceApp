"""测试基础数据查询服务（渠道/账户/分类的读取）。"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from database.models import Channel
from database.seed import (
    DEFAULT_ACCOUNTS,
    DEFAULT_CHANNELS,
    DEFAULT_EXPENSE_CATEGORIES,
    DEFAULT_INCOME_CATEGORIES,
)


def test_list_active_channels(catalog_service):
    names = {c.name for c in catalog_service.list_active_channels()}
    assert names == set(DEFAULT_CHANNELS)


def test_list_active_accounts(catalog_service):
    names = {a.name for a in catalog_service.list_active_accounts()}
    assert names == set(DEFAULT_ACCOUNTS)


def test_list_active_categories(catalog_service):
    income = {c.name for c in catalog_service.list_active_categories("income")}
    expense = {c.name for c in catalog_service.list_active_categories("expense")}
    assert income == set(DEFAULT_INCOME_CATEGORIES)
    assert expense == set(DEFAULT_EXPENSE_CATEGORIES)


def test_list_categories_invalid_type_raises(catalog_service):
    with pytest.raises(ValueError):
        catalog_service.list_active_categories("transfer")


def test_get_other_category(catalog_service):
    other_income = catalog_service.get_other_category("income")
    other_expense = catalog_service.get_other_category("expense")
    assert other_income is not None and other_income.name == "Other"
    assert other_expense is not None and other_expense.name == "Other"
    assert other_income.id != other_expense.id  # 收入/支出的 Other 相互独立


def test_inactive_channel_not_listed(seeded_factory, catalog_service):
    with seeded_factory() as session:
        channel = session.scalar(select(Channel).where(Channel.name == "Salary"))
        channel.is_active = False
        session.commit()
    names = {c.name for c in catalog_service.list_active_channels()}
    assert "Salary" not in names
