"""测试历史记录多级排序与筛选（用户反馈的功能-2）。"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from database.models import Account, Category, Channel
from helpers import EXPENSE, INCOME, create_kwargs, entity_id
from services.exceptions import ValidationError


def _seed_mixed(seeded_factory, transaction_service):
    """4 笔特征明确的交易：
    - 收入 100（9-1，Salary）
    - 支出 50（9-2，Salary）
    - 收入 300（9-3，Bonus）
    - 支出 200（9-4，Bonus）
    """
    salary_id = entity_id(seeded_factory, Channel, "Salary")
    bonus_id = entity_id(seeded_factory, Channel, "Bonus")
    bank_id = entity_id(seeded_factory, Account, "Bank")
    income_cat = entity_id(seeded_factory, Category, "Salary", INCOME)
    expense_cat = entity_id(seeded_factory, Category, "餐饮", EXPENSE)
    transaction_service.create(
        type=INCOME, amount=Decimal("100"), date=date(2026, 9, 1),
        channel_id=salary_id, account_id=bank_id, category_id=income_cat, note="收入100",
    )
    transaction_service.create(
        type=EXPENSE, amount=Decimal("50"), date=date(2026, 9, 2),
        channel_id=salary_id, account_id=bank_id, category_id=expense_cat, note="支出50",
    )
    transaction_service.create(
        type=INCOME, amount=Decimal("300"), date=date(2026, 9, 3),
        channel_id=bonus_id, account_id=bank_id, category_id=income_cat, note="收入300",
    )
    transaction_service.create(
        type=EXPENSE, amount=Decimal("200"), date=date(2026, 9, 4),
        channel_id=bonus_id, account_id=bank_id, category_id=expense_cat, note="支出200",
    )


def _notes(records) -> list[str]:
    return [r.note for r in records]


def _query(transaction_service, **kwargs):
    return transaction_service.list_transactions_page(page_size=100, **kwargs).records


# ---------- 多级排序 ----------

def test_sort_type_asc_then_amount_desc(seeded_factory, transaction_service):
    """用户举的例子：先按类型收入→支出，再按金额从高到低。"""
    _seed_mixed(seeded_factory, transaction_service)
    records = _query(transaction_service, sort=[("type", "asc"), ("amount", "desc")])
    assert _notes(records) == ["收入300", "收入100", "支出200", "支出50"]


def test_sort_amount_desc(seeded_factory, transaction_service):
    _seed_mixed(seeded_factory, transaction_service)
    records = _query(transaction_service, sort=[("amount", "desc")])
    assert _notes(records) == ["收入300", "支出200", "收入100", "支出50"]


def test_sort_type_desc_puts_expenses_first(seeded_factory, transaction_service):
    _seed_mixed(seeded_factory, transaction_service)
    records = _query(transaction_service, sort=[("type", "desc")])
    assert records[0].type == EXPENSE and records[1].type == EXPENSE
    assert records[2].type == INCOME and records[3].type == INCOME


def test_sort_channel_asc(seeded_factory, transaction_service):
    """按渠道名升序：Bonus 在前、Salary 在后；组内按 id 倒序。"""
    _seed_mixed(seeded_factory, transaction_service)
    records = _query(transaction_service, sort=[("channel", "asc")])
    assert _notes(records) == ["支出200", "收入300", "支出50", "收入100"]


def test_sort_channel_deleted_last(seeded_factory, transaction_service):
    """引用已删除渠道的交易在按渠道排序时恒排最后。"""
    _seed_mixed(seeded_factory, transaction_service)
    salary_id = entity_id(seeded_factory, Channel, "Salary")
    with seeded_factory() as session:
        session.delete(session.get(Channel, salary_id))
        session.commit()

    records = _query(transaction_service, sort=[("channel", "asc")])
    assert records[0].channel_name == "Bonus"
    assert records[1].channel_name == "Bonus"
    assert records[2].channel_id is None
    assert records[3].channel_id is None


def test_sort_default_date_desc(seeded_factory, transaction_service):
    _seed_mixed(seeded_factory, transaction_service)
    records = _query(transaction_service)
    assert _notes(records) == ["支出200", "收入300", "支出50", "收入100"]


def test_sort_invalid_rejected(seeded_factory, transaction_service):
    _seed_mixed(seeded_factory, transaction_service)
    with pytest.raises(ValidationError):
        transaction_service.list_transactions_page(sort=[("foo", "asc")])
    with pytest.raises(ValidationError):
        transaction_service.list_transactions_page(sort=[("amount", "up")])
    with pytest.raises(ValidationError):
        transaction_service.list_transactions_page(sort=[("amount",)])


# ---------- 筛选 ----------

def test_filter_type(seeded_factory, transaction_service):
    _seed_mixed(seeded_factory, transaction_service)
    records = _query(transaction_service, filters={"type": EXPENSE})
    assert _notes(records) == ["支出200", "支出50"]  # 日期倒序


def test_filter_channel(seeded_factory, transaction_service):
    _seed_mixed(seeded_factory, transaction_service)
    bonus_id = entity_id(seeded_factory, Channel, "Bonus")
    records = _query(transaction_service, filters={"channel_id": bonus_id})
    assert {r.note for r in records} == {"收入300", "支出200"}


def test_filter_date_range_inclusive(seeded_factory, transaction_service):
    _seed_mixed(seeded_factory, transaction_service)
    records = _query(
        transaction_service,
        filters={"date_from": date(2026, 9, 2), "date_to": date(2026, 9, 3)},
    )
    assert _notes(records) == ["收入300", "支出50"]


def test_filter_account_and_category(seeded_factory, transaction_service):
    _seed_mixed(seeded_factory, transaction_service)
    bank_id = entity_id(seeded_factory, Account, "Bank")
    expense_cat = entity_id(seeded_factory, Category, "餐饮", EXPENSE)
    records = _query(
        transaction_service,
        filters={"account_id": bank_id, "category_id": expense_cat},
    )
    assert _notes(records) == ["支出200", "支出50"]


def test_filter_combined_with_keyword(seeded_factory, transaction_service):
    _seed_mixed(seeded_factory, transaction_service)
    records = _query(transaction_service, keyword="收入", filters={"type": INCOME})
    assert _notes(records) == ["收入300", "收入100"]


def test_filter_with_pagination_total(seeded_factory, transaction_service):
    _seed_mixed(seeded_factory, transaction_service)
    page = transaction_service.list_transactions_page(
        filters={"type": EXPENSE}, page=1, page_size=1
    )
    assert page.total == 2
    assert page.pages == 2
    assert len(page.records) == 1


def test_filter_invalid_type_rejected(seeded_factory, transaction_service):
    _seed_mixed(seeded_factory, transaction_service)
    with pytest.raises(ValidationError):
        transaction_service.list_transactions_page(filters={"type": "transfer"})
