"""测试渠道/账户/分类管理：新增、编辑、停用/启用（需求 §4.1/§4.2/§4.3/§26/§27）。"""

from __future__ import annotations

from decimal import Decimal

import pytest

from database.models import Account, Category, Channel
from helpers import EXPENSE, INCOME, create_kwargs, entity_id
from services.exceptions import NotFoundError, ValidationError


# ================= 渠道 Channel =================

def test_create_channel(catalog_service):
    channel_id = catalog_service.create_channel("稿费收入", "副业")
    info = {c.id: c for c in catalog_service.list_all_channels()}[channel_id]
    assert info.name == "稿费收入"
    assert info.description == "副业"
    assert info.is_active is True
    assert info.transaction_count == 0


def test_create_channel_with_monthly_amount(catalog_service):
    """每月固定金额（用户确认的功能）。"""
    channel_id = catalog_service.create_channel("工资", "", Decimal("3000"))
    info = {c.id: c for c in catalog_service.list_all_channels()}[channel_id]
    assert info.monthly_amount == Decimal("3000")


def test_channel_monthly_amount_negative_rejected(catalog_service):
    with pytest.raises(ValidationError, match="负数"):
        catalog_service.create_channel("X", "", Decimal("-1.00"))


def test_update_channel_monthly_amount(seeded_factory, catalog_service):
    channel_id = entity_id(seeded_factory, Channel, "Salary")
    catalog_service.update_channel(channel_id, "Salary", "", Decimal("3000"))
    info = {c.id: c for c in catalog_service.list_all_channels()}[channel_id]
    assert info.monthly_amount == Decimal("3000")
    # monthly_amount=None 表示保持不变
    catalog_service.update_channel(channel_id, "Salary", "新描述", None)
    info = {c.id: c for c in catalog_service.list_all_channels()}[channel_id]
    assert info.monthly_amount == Decimal("3000")


def test_create_channel_duplicate_name_rejected(catalog_service):
    with pytest.raises(ValidationError, match="已存在"):
        catalog_service.create_channel("Salary")


def test_create_channel_empty_name_rejected(catalog_service):
    for bad in ("", "   "):
        with pytest.raises(ValidationError, match="不能为空"):
            catalog_service.create_channel(bad)


def test_create_channel_too_long_name_rejected(catalog_service):
    with pytest.raises(ValidationError, match="过长"):
        catalog_service.create_channel("x" * 51)


def test_update_channel(seeded_factory, catalog_service):
    channel_id = entity_id(seeded_factory, Channel, "Salary")
    catalog_service.update_channel(channel_id, "正式工资", "每月固定收入")
    info = {c.id: c for c in catalog_service.list_all_channels()}[channel_id]
    assert info.name == "正式工资"
    assert info.description == "每月固定收入"


def test_update_channel_same_name_allowed(seeded_factory, catalog_service):
    channel_id = entity_id(seeded_factory, Channel, "Salary")
    catalog_service.update_channel(channel_id, "Salary", "新描述")  # 不应报「已存在」


def test_update_channel_duplicate_name_rejected(seeded_factory, catalog_service):
    channel_id = entity_id(seeded_factory, Channel, "Salary")
    with pytest.raises(ValidationError, match="已存在"):
        catalog_service.update_channel(channel_id, "Bonus")


def test_update_channel_missing_raises_not_found(catalog_service):
    with pytest.raises(NotFoundError):
        catalog_service.update_channel(99999, "X")


def test_deactivate_channel_preserves_history(seeded_factory, catalog_service, transaction_service):
    """停用后不能新建交易；历史交易完整保留（需求 §4.1）。"""
    tx_id = transaction_service.create(**create_kwargs(seeded_factory, note="停用前"))
    channel_id = entity_id(seeded_factory, Channel, "Salary")

    catalog_service.set_channel_active(channel_id, False)

    with pytest.raises(ValidationError, match="渠道"):
        transaction_service.create(**create_kwargs(seeded_factory))

    record = transaction_service.get(tx_id)
    assert record.channel_name == "Salary"

    assert "Salary" not in {c.name for c in catalog_service.list_active_channels()}
    assert "Salary" in {c.name for c in catalog_service.list_all_channels()}


def test_reactivate_channel(seeded_factory, catalog_service):
    channel_id = entity_id(seeded_factory, Channel, "Salary")
    catalog_service.set_channel_active(channel_id, False)
    catalog_service.set_channel_active(channel_id, True)
    assert "Salary" in {c.name for c in catalog_service.list_active_channels()}


def test_set_channel_active_missing_raises(catalog_service):
    with pytest.raises(NotFoundError):
        catalog_service.set_channel_active(99999, False)


def test_channel_transaction_count(seeded_factory, catalog_service, transaction_service):
    transaction_service.create(**create_kwargs(seeded_factory))
    transaction_service.create(**create_kwargs(seeded_factory, note="第二笔"))
    info = {c.name: c for c in catalog_service.list_all_channels()}["Salary"]
    assert info.transaction_count == 2


# ================= 实体删除（仅限已停用，软外键保障历史）=================

def test_delete_channel_active_rejected(seeded_factory, catalog_service):
    salary_id = entity_id(seeded_factory, Channel, "Salary")
    with pytest.raises(ValidationError, match="先停用"):
        catalog_service.delete_channel(salary_id)


def test_delete_channel_inactive_succeeds_preserving_transactions(
    seeded_factory, catalog_service, transaction_service
):
    tx_id = transaction_service.create(**create_kwargs(seeded_factory))
    salary_id = entity_id(seeded_factory, Channel, "Salary")

    catalog_service.set_channel_active(salary_id, False)
    catalog_service.delete_channel(salary_id)

    assert "Salary" not in {c.name for c in catalog_service.list_all_channels()}
    record = transaction_service.get(tx_id)
    assert record is not None
    assert record.channel_id is None  # 软外键置空，交易保留


def test_delete_account_inactive_succeeds(seeded_factory, catalog_service, transaction_service):
    tx_id = transaction_service.create(**create_kwargs(seeded_factory))
    bank_id = entity_id(seeded_factory, Account, "Bank")

    catalog_service.set_account_active(bank_id, False)
    catalog_service.delete_account(bank_id)

    assert "Bank" not in {a.name for a in catalog_service.list_all_accounts()}
    record = transaction_service.get(tx_id)
    assert record.account_id is None


def test_delete_category_other_rejected(seeded_factory, catalog_service):
    """Other 是自动映射分类，不能删除（需求 §4.5）。"""
    other_id = entity_id(seeded_factory, Category, "Other", EXPENSE)
    with pytest.raises(ValidationError, match="Other"):
        catalog_service.delete_category(other_id)


def test_delete_category_inactive_succeeds(seeded_factory, catalog_service, transaction_service):
    tx_id = transaction_service.create(**create_kwargs(seeded_factory))
    category_id = entity_id(seeded_factory, Category, "餐饮", EXPENSE)

    catalog_service.set_category_active(category_id, False)
    catalog_service.delete_category(category_id)

    assert "餐饮" not in {c.name for c in catalog_service.list_all_categories() if c.type == EXPENSE}
    record = transaction_service.get(tx_id)
    assert record.category_id is None


def test_delete_missing_raises(catalog_service):
    with pytest.raises(NotFoundError):
        catalog_service.delete_channel(99999)
    with pytest.raises(NotFoundError):
        catalog_service.delete_account(99999)
    with pytest.raises(NotFoundError):
        catalog_service.delete_category(99999)


# ================= 账户 Account =================

def test_create_account_with_initial_balance(catalog_service):
    account_id = catalog_service.create_account("证券账户", "股票", Decimal("1000.50"))
    info = {a.id: a for a in catalog_service.list_all_accounts()}[account_id]
    assert info.initial_balance == Decimal("1000.50")
    assert isinstance(info.initial_balance, Decimal)


def test_create_account_balance_rounds_to_cents(catalog_service):
    account_id = catalog_service.create_account("X", "", Decimal("1.005"))
    info = {a.id: a for a in catalog_service.list_all_accounts()}[account_id]
    assert info.initial_balance == Decimal("1.01")


def test_create_account_negative_balance_allowed(catalog_service):
    """信用卡等负债账户允许负初始余额。"""
    account_id = catalog_service.create_account("信用卡", "", Decimal("-500.00"))
    info = {a.id: a for a in catalog_service.list_all_accounts()}[account_id]
    assert info.initial_balance == Decimal("-500.00")


def test_create_account_duplicate_name_rejected(catalog_service):
    with pytest.raises(ValidationError, match="已存在"):
        catalog_service.create_account("Bank")


def test_update_account_initial_balance(seeded_factory, catalog_service):
    """初始余额可随时编辑（需求 §27）。"""
    account_id = entity_id(seeded_factory, Account, "Bank")
    catalog_service.update_account(account_id, "Bank", "", Decimal("8888.88"))
    info = {a.id: a for a in catalog_service.list_all_accounts()}[account_id]
    assert info.initial_balance == Decimal("8888.88")


def test_update_account_invalid_balance_rejected(seeded_factory, catalog_service):
    account_id = entity_id(seeded_factory, Account, "Bank")
    with pytest.raises(ValidationError, match="不是有效数字"):
        catalog_service.update_account(account_id, "Bank", "", Decimal("NaN"))
    with pytest.raises(ValidationError, match="不是有效数字"):
        catalog_service.update_account(account_id, "Bank", "", 100)  # 非 Decimal


def test_update_account_missing_raises(catalog_service):
    with pytest.raises(NotFoundError):
        catalog_service.update_account(99999, "X")


def test_deactivate_account_preserves_history(seeded_factory, catalog_service, transaction_service):
    tx_id = transaction_service.create(**create_kwargs(seeded_factory))
    account_id = entity_id(seeded_factory, Account, "Bank")

    catalog_service.set_account_active(account_id, False)

    with pytest.raises(ValidationError, match="账户"):
        transaction_service.create(**create_kwargs(seeded_factory))
    assert transaction_service.get(tx_id).account_name == "Bank"


# ================= 分类 Category =================

def test_create_category(catalog_service):
    category_id = catalog_service.create_category("稿费", INCOME, "写作收入")
    info = {c.id: c for c in catalog_service.list_all_categories()}[category_id]
    assert info.name == "稿费"
    assert info.type == INCOME
    assert info.description == "写作收入"
    assert info.is_active is True


def test_create_category_duplicate_in_same_type_rejected(catalog_service):
    with pytest.raises(ValidationError, match="已存在"):
        catalog_service.create_category("餐饮", EXPENSE)


def test_create_category_same_name_other_type_allowed(catalog_service):
    """同名分类在收入/支出两个类型下可以并存（逻辑隔离）。"""
    catalog_service.create_category("餐饮", INCOME)  # 不抛异常
    assert "餐饮" in {c.name for c in catalog_service.list_active_categories(EXPENSE)}
    assert "餐饮" in {c.name for c in catalog_service.list_active_categories(INCOME)}


def test_create_category_invalid_type_rejected(catalog_service):
    with pytest.raises(ValidationError, match="类型"):
        catalog_service.create_category("X", "transfer")


def test_update_category_name_and_description(seeded_factory, catalog_service):
    category_id = entity_id(seeded_factory, Category, "餐饮", EXPENSE)
    catalog_service.update_category(category_id, "吃饭", "三餐")
    info = {c.id: c for c in catalog_service.list_all_categories()}[category_id]
    assert info.name == "吃饭"
    assert info.description == "三餐"
    assert info.type == EXPENSE  # 类型保持不变


def test_update_category_duplicate_rejected(seeded_factory, catalog_service):
    category_id = entity_id(seeded_factory, Category, "餐饮", EXPENSE)
    with pytest.raises(ValidationError, match="已存在"):
        catalog_service.update_category(category_id, "出行")


def test_update_category_missing_raises(catalog_service):
    with pytest.raises(NotFoundError):
        catalog_service.update_category(99999, "X")


def test_deactivate_category_preserves_history(seeded_factory, catalog_service, transaction_service):
    tx_id = transaction_service.create(**create_kwargs(seeded_factory))  # 分类 = 餐饮
    category_id = entity_id(seeded_factory, Category, "餐饮", EXPENSE)

    catalog_service.set_category_active(category_id, False)

    with pytest.raises(ValidationError, match="分类"):
        transaction_service.create(**create_kwargs(seeded_factory))
    assert transaction_service.get(tx_id).category_name == "餐饮"


def test_deactivate_other_category_rejected(seeded_factory, catalog_service):
    """Other 是自动映射分类，不能停用（需求 §4.5）。"""
    other_id = entity_id(seeded_factory, Category, "Other", EXPENSE)
    with pytest.raises(ValidationError, match="Other"):
        catalog_service.set_category_active(other_id, False)


def test_reactivate_category(seeded_factory, catalog_service):
    category_id = entity_id(seeded_factory, Category, "餐饮", EXPENSE)
    catalog_service.set_category_active(category_id, False)
    catalog_service.set_category_active(category_id, True)
    assert "餐饮" in {c.name for c in catalog_service.list_active_categories(EXPENSE)}


def test_category_transaction_count(seeded_factory, catalog_service, transaction_service):
    transaction_service.create(**create_kwargs(seeded_factory))
    expenses = {
        c.name: c for c in catalog_service.list_all_categories() if c.type == EXPENSE
    }
    assert expenses["餐饮"].transaction_count == 1
