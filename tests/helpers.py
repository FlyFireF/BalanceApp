"""测试辅助函数：实体 id 查询与交易参数构造（多个测试文件共用）。"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select

from database.models import Account, Category, CategoryType, Channel

INCOME = CategoryType.INCOME.value
EXPENSE = CategoryType.EXPENSE.value


def entity_id(seeded_factory, model, name: str, type_=None) -> int:
    """按名称（+类型）查实体 id。"""
    with seeded_factory() as session:
        stmt = select(model).where(model.name == name)
        if type_ is not None:
            stmt = stmt.where(model.type == type_)
        entity = session.scalar(stmt)
        assert entity is not None, f"未找到 {name!r}"
        return entity.id


def create_kwargs(seeded_factory, **overrides) -> dict:
    """构造一笔「支出 50 元」的默认交易参数，可整体覆盖。"""
    kwargs = dict(
        type=EXPENSE,
        amount=Decimal("50.00"),
        date=date(2026, 9, 18),
        channel_id=entity_id(seeded_factory, Channel, "Salary"),
        account_id=entity_id(seeded_factory, Account, "Bank"),
        category_id=entity_id(seeded_factory, Category, "餐饮", EXPENSE),
        note="午饭",
        tags="food,lunch",
    )
    kwargs.update(overrides)
    return kwargs


def seed_official_scenario(seeded_factory, transaction_service) -> None:
    """需求 §51 官方测试数据：Salary 渠道 + Bank 账户 4 笔交易。"""
    channel_id = entity_id(seeded_factory, Channel, "Salary")
    account_id = entity_id(seeded_factory, Account, "Bank")
    income_cat = entity_id(seeded_factory, Category, "Salary", INCOME)
    expense_cat = entity_id(seeded_factory, Category, "餐饮", EXPENSE)

    transaction_service.create(
        type=INCOME, amount=Decimal("5000"), date=date(2026, 8, 1),
        channel_id=channel_id, account_id=account_id, category_id=income_cat,
    )
    transaction_service.create(
        type=EXPENSE, amount=Decimal("1000"), date=date(2026, 8, 10),
        channel_id=channel_id, account_id=account_id, category_id=expense_cat,
    )
    transaction_service.create(
        type=INCOME, amount=Decimal("3000"), date=date(2026, 9, 1),
        channel_id=channel_id, account_id=account_id, category_id=income_cat,
    )
    transaction_service.create(
        type=EXPENSE, amount=Decimal("500"), date=date(2026, 9, 10),
        channel_id=channel_id, account_id=account_id, category_id=expense_cat,
    )
