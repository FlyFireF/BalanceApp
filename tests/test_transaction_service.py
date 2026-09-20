"""测试交易服务：创建 / 编辑 / 删除收入与支出 + 全部校验规则（需求 §6/§7/§8/§4.5）。"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from database.models import Account, Category, Channel
from helpers import EXPENSE, INCOME, create_kwargs as _create_kwargs, entity_id as _entity_id
from services.exceptions import NotFoundError, ValidationError


# ---------- 创建 ----------

def test_create_income(seeded_factory, transaction_service):
    tx_id = transaction_service.create(
        **_create_kwargs(
            seeded_factory,
            type=INCOME,
            amount=Decimal("5000.00"),
            category_id=_entity_id(seeded_factory, Category, "Salary", INCOME),
            note="9月工资",
        )
    )
    records = transaction_service.list_transactions()
    assert len(records) == 1
    record = records[0]
    assert record.id == tx_id
    assert record.type == INCOME
    assert record.amount == Decimal("5000.00")
    assert record.date == date(2026, 9, 18)
    assert record.channel_name == "Salary"
    assert record.account_name == "Bank"
    assert record.category_name == "Salary"
    assert record.note == "9月工资"


def test_create_expense(seeded_factory, transaction_service):
    tx_id = transaction_service.create(**_create_kwargs(seeded_factory))
    record = transaction_service.get(tx_id)
    assert record is not None
    assert record.type == EXPENSE
    assert record.amount == Decimal("50.00")
    assert record.category_name == "餐饮"


# ---------- 更新 ----------

def test_update_income(seeded_factory, transaction_service):
    kwargs = _create_kwargs(
        seeded_factory,
        type=INCOME,
        category_id=_entity_id(seeded_factory, Category, "Salary", INCOME),
    )
    tx_id = transaction_service.create(**kwargs)
    transaction_service.update(
        tx_id, **{**kwargs, "amount": Decimal("6000.00"), "note": "改过的备注"}
    )
    record = transaction_service.get(tx_id)
    assert record.amount == Decimal("6000.00")
    assert record.note == "改过的备注"


def test_update_expense(seeded_factory, transaction_service):
    kwargs = _create_kwargs(seeded_factory)
    tx_id = transaction_service.create(**kwargs)
    transaction_service.update(tx_id, **{**kwargs, "amount": Decimal("88.88")})
    record = transaction_service.get(tx_id)
    assert record.amount == Decimal("88.88")
    assert len(transaction_service.list_transactions()) == 1


def test_update_missing_raises_not_found(seeded_factory, transaction_service):
    with pytest.raises(NotFoundError):
        transaction_service.update(99999, **_create_kwargs(seeded_factory))


# ---------- 删除 ----------

def test_delete_income(seeded_factory, transaction_service):
    tx_id = transaction_service.create(
        **_create_kwargs(
            seeded_factory,
            type=INCOME,
            category_id=_entity_id(seeded_factory, Category, "Salary", INCOME),
        )
    )
    transaction_service.delete(tx_id)
    assert transaction_service.list_transactions() == []


def test_delete_expense(seeded_factory, transaction_service):
    tx_id = transaction_service.create(**_create_kwargs(seeded_factory))
    transaction_service.delete(tx_id)
    assert transaction_service.list_transactions() == []


def test_delete_only_removes_target(seeded_factory, transaction_service):
    keep_id = transaction_service.create(**_create_kwargs(seeded_factory, note="保留"))
    remove_id = transaction_service.create(**_create_kwargs(seeded_factory, note="删除"))
    transaction_service.delete(remove_id)
    remaining = transaction_service.list_transactions()
    assert [r.id for r in remaining] == [keep_id]


def test_delete_missing_raises_not_found(transaction_service):
    with pytest.raises(NotFoundError):
        transaction_service.delete(99999)


# ---------- Other 自动映射（需求 §4.5）----------

def test_expense_without_category_maps_to_other(seeded_factory, transaction_service):
    kwargs = _create_kwargs(seeded_factory)
    kwargs.pop("category_id")
    tx_id = transaction_service.create(**kwargs)
    record = transaction_service.get(tx_id)
    assert record.category_name == "Other"
    assert record.category_id == _entity_id(seeded_factory, Category, "Other", EXPENSE)


def test_income_without_category_maps_to_other(seeded_factory, transaction_service):
    kwargs = _create_kwargs(seeded_factory, type=INCOME)
    kwargs.pop("category_id")
    tx_id = transaction_service.create(**kwargs)
    record = transaction_service.get(tx_id)
    assert record.category_name == "Other"
    assert record.category_id == _entity_id(seeded_factory, Category, "Other", INCOME)


# ---------- 校验规则 ----------

def test_category_type_mismatch_rejected(seeded_factory, transaction_service):
    income_category_id = _entity_id(seeded_factory, Category, "Salary", INCOME)
    with pytest.raises(ValidationError, match="类型"):
        transaction_service.create(
            **_create_kwargs(seeded_factory, category_id=income_category_id)
        )


def test_inactive_channel_rejected(seeded_factory, transaction_service):
    channel_id = _entity_id(seeded_factory, Channel, "Salary")
    with seeded_factory() as session:
        channel = session.get(Channel, channel_id)
        channel.is_active = False
        session.commit()
    with pytest.raises(ValidationError, match="渠道"):
        transaction_service.create(**_create_kwargs(seeded_factory))


def test_update_allows_unchanged_inactive_channel(seeded_factory, transaction_service, catalog_service):
    """放宽规则：编辑引用已停用渠道的历史交易（引用不变）→ 允许，只改备注。"""
    tx_id = transaction_service.create(**_create_kwargs(seeded_factory))
    channel_id = _entity_id(seeded_factory, Channel, "Salary")
    catalog_service.set_channel_active(channel_id, False)

    transaction_service.update(
        tx_id, **{**_create_kwargs(seeded_factory), "note": "只改备注"}
    )

    record = transaction_service.get(tx_id)
    assert record.note == "只改备注"
    assert record.channel_name == "Salary"


def test_update_rejects_switching_to_inactive_channel(seeded_factory, transaction_service, catalog_service):
    """更换引用仍要求实体启用。"""
    tx_id = transaction_service.create(**_create_kwargs(seeded_factory))  # 引用 Salary
    bonus_id = _entity_id(seeded_factory, Channel, "Bonus")
    catalog_service.set_channel_active(bonus_id, False)

    with pytest.raises(ValidationError, match="渠道"):
        transaction_service.update(
            tx_id, **{**_create_kwargs(seeded_factory), "channel_id": bonus_id}
        )


def test_update_allows_unchanged_deleted_channel(seeded_factory, transaction_service):
    """渠道被删除后（引用置空），编辑该交易仍被允许（软外键原则）。"""
    tx_id = transaction_service.create(**_create_kwargs(seeded_factory))
    channel_id = _entity_id(seeded_factory, Channel, "Salary")
    with seeded_factory() as session:
        session.delete(session.get(Channel, channel_id))
        session.commit()

    record_before = transaction_service.get(tx_id)
    assert record_before.channel_id is None
    assert record_before.channel_name is None

    account_id = _entity_id(seeded_factory, Account, "Bank")
    category_id = _entity_id(seeded_factory, Category, "餐饮", EXPENSE)
    transaction_service.update(
        tx_id,
        type=EXPENSE,
        amount=Decimal("50.00"),
        date=date(2026, 9, 18),
        channel_id=None,  # 保持已删除的引用
        account_id=account_id,
        category_id=category_id,
        note="改",
        tags="",
    )

    record = transaction_service.get(tx_id)
    assert record.note == "改"
    assert record.channel_id is None


def test_nonexistent_channel_rejected(seeded_factory, transaction_service):
    with pytest.raises(ValidationError, match="渠道"):
        transaction_service.create(**_create_kwargs(seeded_factory, channel_id=99999))


def test_nonexistent_account_rejected(seeded_factory, transaction_service):
    with pytest.raises(ValidationError, match="账户"):
        transaction_service.create(**_create_kwargs(seeded_factory, account_id=99999))


def test_nonexistent_category_rejected(seeded_factory, transaction_service):
    with pytest.raises(ValidationError, match="分类"):
        transaction_service.create(**_create_kwargs(seeded_factory, category_id=99999))


def test_amount_zero_rejected(seeded_factory, transaction_service):
    with pytest.raises(ValidationError, match="大于 0"):
        transaction_service.create(**_create_kwargs(seeded_factory, amount=Decimal("0.00")))


def test_amount_negative_rejected(seeded_factory, transaction_service):
    with pytest.raises(ValidationError, match="大于 0"):
        transaction_service.create(**_create_kwargs(seeded_factory, amount=Decimal("-5.00")))


def test_amount_nan_rejected(seeded_factory, transaction_service):
    with pytest.raises(ValidationError, match="不是有效数字"):
        transaction_service.create(**_create_kwargs(seeded_factory, amount=Decimal("NaN")))


def test_amount_non_decimal_rejected(seeded_factory, transaction_service):
    with pytest.raises(ValidationError, match="不是有效数字"):
        transaction_service.create(**_create_kwargs(seeded_factory, amount=50))


def test_amount_rounds_to_cents(seeded_factory, transaction_service):
    """超过两位小数的金额四舍五入到分（与存储策略一致）。"""
    tx_id = transaction_service.create(
        **_create_kwargs(seeded_factory, amount=Decimal("12.345"))
    )
    assert transaction_service.get(tx_id).amount == Decimal("12.35")


def test_amount_rounding_to_zero_rejected(seeded_factory, transaction_service):
    with pytest.raises(ValidationError, match="大于 0"):
        transaction_service.create(**_create_kwargs(seeded_factory, amount=Decimal("0.004")))


def test_invalid_type_rejected(seeded_factory, transaction_service):
    with pytest.raises(ValidationError, match="类型"):
        transaction_service.create(**_create_kwargs(seeded_factory, type="transfer"))


def test_datetime_rejected_as_date(seeded_factory, transaction_service):
    with pytest.raises(ValidationError, match="日期"):
        transaction_service.create(
            **_create_kwargs(seeded_factory, date=datetime(2026, 9, 18, 10, 30))
        )


def test_note_too_long_rejected(seeded_factory, transaction_service):
    with pytest.raises(ValidationError, match="备注"):
        transaction_service.create(**_create_kwargs(seeded_factory, note="x" * 501))


def test_tags_too_long_rejected(seeded_factory, transaction_service):
    with pytest.raises(ValidationError, match="标签"):
        transaction_service.create(**_create_kwargs(seeded_factory, tags="x" * 201))


def test_note_and_tags_are_stripped(seeded_factory, transaction_service):
    tx_id = transaction_service.create(
        **_create_kwargs(seeded_factory, note="  午饭  ", tags=" food ")
    )
    record = transaction_service.get(tx_id)
    assert record.note == "午饭"
    assert record.tags == "food"


# ---------- 查询 ----------

def test_list_ordered_by_date_desc(seeded_factory, transaction_service):
    for day in (1, 3, 2):
        transaction_service.create(
            **_create_kwargs(seeded_factory, date=date(2026, 9, day), note=f"d{day}")
        )
    dates = [r.date for r in transaction_service.list_transactions()]
    assert dates == [date(2026, 9, 3), date(2026, 9, 2), date(2026, 9, 1)]


def test_list_empty_when_no_transactions(transaction_service):
    assert transaction_service.list_transactions() == []


def test_get_missing_returns_none(transaction_service):
    assert transaction_service.get(99999) is None
