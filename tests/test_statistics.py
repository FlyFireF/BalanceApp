"""测试月度统计服务（需求 §16-§23/§25/§42/§51）。

包含需求 §51 的官方验收数据，该测试必须通过。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from datetime import datetime

from sqlalchemy import select

from database.models import Account, Category, Channel
from helpers import EXPENSE, INCOME, entity_id, seed_official_scenario
from services.exceptions import ValidationError
from services.statistics_service import balance_percent


def _set_channel_created(seeded_factory, name: str, created: date) -> None:
    """把渠道创建时间设为指定日期（每月固定金额的起算月）。"""
    with seeded_factory() as session:
        channel = session.scalar(select(Channel).where(Channel.name == name))
        channel.created_at = datetime(created.year, created.month, created.day, 10, 0, 0)
        session.commit()


def _salary(stats) -> "ChannelStatistics":
    return next(c for c in stats.channels if c.channel_name == "Salary")


# ---------- 需求 §51 官方验收 ----------

def test_official_scenario_september(seeded_factory, transaction_service, statistics_service):
    """需求 §51：Dashboard 选 2026-09 必须得到文档中的精确结果。

    注意：余额百分比按用户确认的月度口径（本月净额/本月收入），
    即 (3000-500)/3000 = 83.33%（原文档 §19 的累计口径 81.25% 已被取代）。
    """
    seed_official_scenario(seeded_factory, transaction_service)
    stats = statistics_service.month_statistics(2026, 9)

    assert stats.year == 2026 and stats.month == 9
    assert stats.month_income == Decimal("3000")
    assert stats.month_expense == Decimal("500")
    assert stats.month_net == Decimal("2500")

    salary = _salary(stats)
    assert salary.month_income == Decimal("3000")
    assert salary.month_expense == Decimal("500")
    assert salary.cumulative_income == Decimal("8000")
    assert salary.cumulative_expense == Decimal("1500")
    assert salary.balance == Decimal("6500")
    assert salary.balance_percent == Decimal("83.33")  # 月度口径

    bank = next(a for a in stats.accounts if a.account_name == "Bank")
    assert bank.initial_balance == Decimal("0")
    assert bank.balance == Decimal("6500")  # 0 + 8000 - 1500


def test_official_scenario_august(seeded_factory, transaction_service, statistics_service):
    """同数据看 2026-08：9 月交易不计入 8 月累计。"""
    seed_official_scenario(seeded_factory, transaction_service)
    stats = statistics_service.month_statistics(2026, 8)

    assert stats.month_income == Decimal("5000")
    assert stats.month_expense == Decimal("1000")
    assert stats.month_net == Decimal("4000")

    salary = _salary(stats)
    assert salary.cumulative_income == Decimal("5000")
    assert salary.cumulative_expense == Decimal("1000")
    assert salary.balance == Decimal("4000")
    assert salary.balance_percent == Decimal("80.00")  # 月度口径：(5000-1000)/5000


# ---------- 本月 vs 累计（需求 §25）----------

def test_month_and_cumulative_are_distinct(seeded_factory, transaction_service, statistics_service):
    """10 月的交易不得影响 9 月的累计数据。"""
    seed_official_scenario(seeded_factory, transaction_service)
    channel_id = entity_id(seeded_factory, Channel, "Salary")
    account_id = entity_id(seeded_factory, Account, "Bank")
    income_cat = entity_id(seeded_factory, Category, "Salary", INCOME)
    transaction_service.create(
        type=INCOME, amount=Decimal("100"), date=date(2026, 10, 5),
        channel_id=channel_id, account_id=account_id, category_id=income_cat,
    )

    stats = statistics_service.month_statistics(2026, 9)
    assert _salary(stats).cumulative_income == Decimal("8000")  # 不含 10 月
    assert stats.month_income == Decimal("3000")


def test_no_current_month_transactions(seeded_factory, transaction_service, statistics_service):
    """过去有交易、本月无交易：本月为 0，累计仍正确。"""
    seed_official_scenario(seeded_factory, transaction_service)
    stats = statistics_service.month_statistics(2026, 12)

    assert stats.month_income == Decimal("0")
    assert stats.month_expense == Decimal("0")
    assert stats.month_net == Decimal("0")
    assert _salary(stats).cumulative_income == Decimal("8000")
    assert _salary(stats).cumulative_expense == Decimal("1500")


def test_cross_year_boundary(seeded_factory, transaction_service, statistics_service):
    """跨年：2025-12 累计只含 ≤2025-12-31，2026-01 含全部。"""
    channel_id = entity_id(seeded_factory, Channel, "Salary")
    account_id = entity_id(seeded_factory, Account, "Bank")
    income_cat = entity_id(seeded_factory, Category, "Salary", INCOME)
    transaction_service.create(
        type=INCOME, amount=Decimal("100"), date=date(2025, 12, 31),
        channel_id=channel_id, account_id=account_id, category_id=income_cat,
    )
    transaction_service.create(
        type=INCOME, amount=Decimal("200"), date=date(2026, 1, 1),
        channel_id=channel_id, account_id=account_id, category_id=income_cat,
    )

    assert _salary(statistics_service.month_statistics(2025, 12)).cumulative_income == Decimal("100")
    assert _salary(statistics_service.month_statistics(2026, 1)).cumulative_income == Decimal("300")


# ---------- 百分比边界（需求 §19/§20）----------

def test_balance_percent_none_when_no_income(seeded_factory, transaction_service, statistics_service):
    """累计收入 = 0 → N/A（None），余额照实显示。"""
    channel_id = entity_id(seeded_factory, Channel, "Salary")
    account_id = entity_id(seeded_factory, Account, "Bank")
    expense_cat = entity_id(seeded_factory, Category, "餐饮", EXPENSE)
    transaction_service.create(
        type=EXPENSE, amount=Decimal("50"), date=date(2026, 9, 5),
        channel_id=channel_id, account_id=account_id, category_id=expense_cat,
    )

    salary = _salary(statistics_service.month_statistics(2026, 9))
    assert salary.cumulative_income == Decimal("0")
    assert salary.balance == Decimal("-50")
    assert salary.balance_percent is None


def test_negative_balance_percent_zero(seeded_factory, transaction_service, statistics_service):
    """余额 < 0 → 百分比 0%（UI 用红色），余额保留真实负数。"""
    channel_id = entity_id(seeded_factory, Channel, "Salary")
    account_id = entity_id(seeded_factory, Account, "Bank")
    income_cat = entity_id(seeded_factory, Category, "Salary", INCOME)
    expense_cat = entity_id(seeded_factory, Category, "餐饮", EXPENSE)
    transaction_service.create(
        type=INCOME, amount=Decimal("5000"), date=date(2026, 9, 1),
        channel_id=channel_id, account_id=account_id, category_id=income_cat,
    )
    transaction_service.create(
        type=EXPENSE, amount=Decimal("6000"), date=date(2026, 9, 2),
        channel_id=channel_id, account_id=account_id, category_id=expense_cat,
    )

    salary = _salary(statistics_service.month_statistics(2026, 9))
    assert salary.balance == Decimal("-1000")
    assert salary.balance_percent == Decimal("0")


def test_balance_percent_pure_function_boundaries():
    """余额 > 累计收入 → 封顶 100%。正常金额约束下无法通过交易构造，
    直接测试纯函数（需求 §20）。"""
    assert balance_percent(Decimal("100"), Decimal("150")) == Decimal("100")
    assert balance_percent(Decimal("0"), Decimal("0")) is None
    assert balance_percent(Decimal("0"), Decimal("-50")) is None
    assert balance_percent(Decimal("5000"), Decimal("-1000")) == Decimal("0")
    assert balance_percent(Decimal("300"), Decimal("100")) == Decimal("33.33")  # 四舍五入
    assert balance_percent(Decimal("8000"), Decimal("6500")) == Decimal("81.25")


# ---------- 空数据与实体状态 ----------

def test_empty_database(seeded_factory, statistics_service):
    """需求 §42：无任何交易时全为 0、百分比 N/A、无 None/NaN。"""
    stats = statistics_service.month_statistics(2026, 9)
    assert stats.month_income == Decimal("0")
    assert stats.month_expense == Decimal("0")
    assert stats.month_net == Decimal("0")
    assert len(stats.channels) == 5  # 默认启用渠道全部展示
    assert all(c.balance == Decimal("0") for c in stats.channels)
    assert all(c.balance_percent is None for c in stats.channels)
    assert len(stats.accounts) == 4
    assert all(a.balance == a.initial_balance == Decimal("0") for a in stats.accounts)


def test_account_initial_balance_included(seeded_factory, transaction_service, catalog_service, statistics_service):
    """需求 §27/§25：账户余额 = 初始余额 + 累计净流入。"""
    bank_id = entity_id(seeded_factory, Account, "Bank")
    catalog_service.update_account(bank_id, "Bank", "", Decimal("5000"))
    seed_official_scenario(seeded_factory, transaction_service)

    bank = next(a for a in statistics_service.month_statistics(2026, 9).accounts
                if a.account_name == "Bank")
    assert bank.initial_balance == Decimal("5000")
    assert bank.balance == Decimal("11500")  # 5000 + 8000 - 1500


def test_deactivated_channel_with_history_still_shown(seeded_factory, transaction_service, catalog_service, statistics_service):
    """停用渠道的历史数据不丢失：仍有交易则继续展示（需求 §4.1）。"""
    seed_official_scenario(seeded_factory, transaction_service)
    channel_id = entity_id(seeded_factory, Channel, "Salary")
    catalog_service.set_channel_active(channel_id, False)

    salary = _salary(statistics_service.month_statistics(2026, 9))
    assert salary is not None
    assert salary.is_active is False
    assert salary.cumulative_income == Decimal("8000")


def test_inactive_channel_without_history_hidden(seeded_factory, catalog_service, statistics_service):
    """停用且无交易的渠道不展示（避免空白噪音）。"""
    channel_id = catalog_service.create_channel("临时渠道")
    catalog_service.set_channel_active(channel_id, False)

    stats = statistics_service.month_statistics(2026, 9)
    assert all(c.channel_name != "临时渠道" for c in stats.channels)


# ---------- 每月固定金额（用户确认的功能）----------

def test_channel_monthly_fixed_amount(seeded_factory, catalog_service, transaction_service, statistics_service):
    """每月固定金额计入本月收入与累计收入（从创建月份起算）。"""
    salary_id = entity_id(seeded_factory, Channel, "Salary")
    catalog_service.update_channel(salary_id, "Salary", "", Decimal("3000"))
    _set_channel_created(seeded_factory, "Salary", date(2026, 8, 1))
    seed_official_scenario(seeded_factory, transaction_service)

    stats = statistics_service.month_statistics(2026, 9)
    assert stats.month_income == Decimal("6000")  # 3000 真实 + 3000 固定
    assert stats.month_expense == Decimal("500")

    salary = _salary(stats)
    assert salary.monthly_amount == Decimal("3000")
    assert salary.month_income == Decimal("6000")
    assert salary.cumulative_income == Decimal("14000")  # 8000 真实 + 3000×2 个月（8、9月）
    assert salary.balance == Decimal("12500")
    assert salary.balance_percent == Decimal("91.67")  # 月度口径：(6000-500)/6000


def test_channel_monthly_not_counted_before_creation(seeded_factory, catalog_service, transaction_service, statistics_service):
    """固定金额不从渠道创建前的月份起算。"""
    salary_id = entity_id(seeded_factory, Channel, "Salary")
    catalog_service.update_channel(salary_id, "Salary", "", Decimal("3000"))
    _set_channel_created(seeded_factory, "Salary", date(2026, 9, 1))
    seed_official_scenario(seeded_factory, transaction_service)

    aug = statistics_service.month_statistics(2026, 8)
    assert aug.month_income == Decimal("5000")  # 仅真实交易，无固定金额
    assert _salary(aug).cumulative_income == Decimal("5000")


def test_channel_monthly_not_counted_when_inactive(seeded_factory, catalog_service, transaction_service, statistics_service):
    salary_id = entity_id(seeded_factory, Channel, "Salary")
    catalog_service.update_channel(salary_id, "Salary", "", Decimal("3000"))
    _set_channel_created(seeded_factory, "Salary", date(2026, 8, 1))
    seed_official_scenario(seeded_factory, transaction_service)
    catalog_service.set_channel_active(salary_id, False)

    stats = statistics_service.month_statistics(2026, 9)
    assert stats.month_income == Decimal("3000")  # 仅真实交易


def test_monthly_percent_resets_each_month(seeded_factory, catalog_service, transaction_service, statistics_service):
    """用户确认的月度口径验收：9 月固定 3000、花 2700 → 剩余 10%；
    10 月自动补充 3000 固定收入、无支出 → 剩余恢复到 100%。"""
    salary_id = entity_id(seeded_factory, Channel, "Salary")
    catalog_service.update_channel(salary_id, "Salary", "", Decimal("3000"))
    _set_channel_created(seeded_factory, "Salary", date(2026, 8, 1))
    channel_id = salary_id
    account_id = entity_id(seeded_factory, Account, "Bank")
    expense_cat = entity_id(seeded_factory, Category, "餐饮", EXPENSE)
    transaction_service.create(
        type=EXPENSE, amount=Decimal("2700"), date=date(2026, 9, 15),
        channel_id=channel_id, account_id=account_id, category_id=expense_cat,
        note="9月开销",
    )

    sept = _salary(statistics_service.month_statistics(2026, 9))
    assert sept.month_income == Decimal("3000")  # 固定收入
    assert sept.month_expense == Decimal("2700")
    assert sept.balance_percent == Decimal("10.00")  # (3000-2700)/3000

    october = _salary(statistics_service.month_statistics(2026, 10))
    assert october.month_income == Decimal("3000")  # 自动补充固定收入
    assert october.month_expense == Decimal("0")
    assert october.balance_percent == Decimal("100.00")  # 月度剩余恢复 100%


def test_deleted_channel_transactions_keep_month_totals(seeded_factory, transaction_service, statistics_service):
    """软外键原则：渠道被删除后，其交易仍计入本月总额（仅渠道卡片不再显示）。"""
    seed_official_scenario(seeded_factory, transaction_service)
    with seeded_factory() as session:
        channel = session.scalar(select(Channel).where(Channel.name == "Salary"))
        session.delete(channel)
        session.commit()

    stats = statistics_service.month_statistics(2026, 9)
    assert stats.month_income == Decimal("3000")  # 交易仍在统计内
    assert stats.month_expense == Decimal("500")
    assert all(c.channel_name != "Salary" for c in stats.channels)  # 渠道卡片不再显示


# ---------- 输入校验 ----------

def test_invalid_month_rejected(statistics_service):
    with pytest.raises(ValidationError, match="月份"):
        statistics_service.month_statistics(2026, 13)
