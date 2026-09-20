"""测试四个核心模型的基本约束与行为（需求 §4）。"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from database.models import (
    Account,
    Category,
    CategoryType,
    Channel,
    Transaction,
)


# ---------- Channel ----------

def test_channel_create(empty_session):
    channel = Channel(name="Salary")
    empty_session.add(channel)
    empty_session.commit()
    assert channel.id is not None
    assert channel.is_active is True
    assert channel.description == ""
    assert channel.created_at is not None
    assert channel.updated_at is not None


def test_channel_name_unique(empty_session):
    empty_session.add(Channel(name="Salary"))
    empty_session.commit()
    empty_session.add(Channel(name="Salary"))
    with pytest.raises(IntegrityError):
        empty_session.commit()
    empty_session.rollback()


def test_updated_at_changes_on_update(empty_session):
    channel = Channel(name="Salary", created_at=datetime(2020, 1, 1))
    empty_session.add(channel)
    empty_session.commit()
    old_updated_at = channel.updated_at

    channel.name = "Salary Renamed"
    empty_session.commit()

    assert channel.updated_at >= old_updated_at
    assert channel.updated_at > channel.created_at


# ---------- Account ----------

def test_account_initial_balance_roundtrip(empty_session):
    account = Account(name="Bank", initial_balance=Decimal("1234.56"))
    empty_session.add(account)
    empty_session.commit()
    assert account.initial_balance == Decimal("1234.56")
    assert isinstance(account.initial_balance, Decimal)


def test_account_initial_balance_stored_as_cents(empty_session):
    account = Account(name="Bank", initial_balance=Decimal("1234.56"))
    empty_session.add(account)
    empty_session.commit()
    raw = empty_session.execute(text("SELECT initial_balance FROM accounts")).scalar()
    assert raw == 123456  # 数据库中存整数「分」


# ---------- Category ----------

def test_category_income_and_expense_same_name_allowed(empty_session):
    """同名分类在收入/支出两个类型下可以并存（逻辑隔离）。"""
    empty_session.add(Category(name="Other", type=CategoryType.INCOME.value))
    empty_session.add(Category(name="Other", type=CategoryType.EXPENSE.value))
    empty_session.commit()  # 不应抛异常


def test_category_name_unique_within_type(empty_session):
    empty_session.add(Category(name="Other", type=CategoryType.INCOME.value))
    empty_session.commit()
    empty_session.add(Category(name="Other", type=CategoryType.INCOME.value))
    with pytest.raises(IntegrityError):
        empty_session.commit()
    empty_session.rollback()


def test_category_invalid_type_rejected(empty_session):
    empty_session.add(Category(name="Bad", type="transfer"))
    with pytest.raises(IntegrityError):
        empty_session.commit()
    empty_session.rollback()


# ---------- Transaction ----------

def test_transaction_create_and_relationships(seeded_session, make_transaction):
    tx = make_transaction(note="午饭", tags="food")
    assert tx.id is not None
    assert tx.channel.name == "Salary"
    assert tx.account.name == "Bank"
    assert tx.category.name == "Other"
    assert tx.category.type == CategoryType.EXPENSE.value
    assert tx.note == "午饭"
    assert tx.tags == "food"


def test_transaction_amount_decimal_exactness(seeded_session, make_transaction):
    """0.1 + 0.2 必须恒等于 0.3：金额以「分」存整数，全程不经过 float。"""
    make_transaction(amount=Decimal("0.10"))
    make_transaction(amount=Decimal("0.20"))
    total = sum(
        (tx.amount for tx in seeded_session.scalars(select(Transaction))),
        Decimal("0"),
    )
    assert total == Decimal("0.30")


def test_transaction_amount_stored_as_cents(seeded_session, make_transaction):
    make_transaction(amount=Decimal("1234.56"))
    raw = seeded_session.execute(text("SELECT amount FROM transactions")).scalar()
    assert raw == 123456


def test_transaction_negative_amount_rejected(seeded_session, make_transaction):
    with pytest.raises(IntegrityError):
        make_transaction(amount=Decimal("-1.00"))
    seeded_session.rollback()


def test_transaction_zero_amount_rejected(seeded_session, make_transaction):
    with pytest.raises(IntegrityError):
        make_transaction(amount=Decimal("0.00"))
    seeded_session.rollback()


def test_transaction_invalid_type_rejected(seeded_session, make_transaction):
    with pytest.raises(IntegrityError):
        make_transaction(type="transfer")
    seeded_session.rollback()


def test_transaction_category_nullable_soft_fk(seeded_session, make_transaction):
    """软外键：category_id 允许 NULL（实体被删除时交易不受影响）。

    新建交易的必填校验在服务层完成（未选分类自动映射 Other，需求 §4.5）。
    """
    tx = make_transaction(category_id=None)
    assert tx.category_id is None
    assert tx.category is None


def test_deleting_channel_does_not_affect_transactions(seeded_session, make_transaction):
    """核心原则：删除渠道后历史交易保留、引用置空（ON DELETE SET NULL）。"""
    tx = make_transaction(note="历史交易")
    channel = seeded_session.get(Channel, tx.channel_id)

    seeded_session.delete(channel)
    seeded_session.commit()

    reloaded = seeded_session.get(Transaction, tx.id)
    assert reloaded is not None  # 交易仍在
    assert reloaded.channel_id is None  # 引用置空
    assert reloaded.amount == Decimal("50.00")
    assert reloaded.note == "历史交易"


def test_transaction_channel_foreign_key_enforced(seeded_session, make_transaction):
    with pytest.raises(IntegrityError):
        make_transaction(channel_id=99999)
    seeded_session.rollback()


def test_transaction_date_roundtrip(seeded_session, make_transaction):
    tx = make_transaction(date=date(2026, 9, 18))
    assert tx.date == date(2026, 9, 18)
    assert isinstance(tx.date, date)


def test_transaction_defaults(seeded_session, make_transaction):
    tx = make_transaction()
    assert tx.note == ""
    assert tx.tags == ""
    assert tx.created_at is not None
