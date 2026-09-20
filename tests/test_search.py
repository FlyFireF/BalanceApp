"""测试交易搜索（需求 §13）：金额 / 备注 / 渠道 / 账户 / 分类 / 标签。"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from helpers import create_kwargs


def _seed_search_data(seeded_factory, transaction_service) -> None:
    """三笔可搜索的测试交易。"""
    transaction_service.create(**create_kwargs(seeded_factory))  # 餐饮 50.00 午饭 food,lunch
    transaction_service.create(
        **create_kwargs(
            seeded_factory,
            amount=Decimal("1234.56"),
            note="九月房租",
            tags="rent",
            date=date(2026, 9, 1),
        )
    )
    transaction_service.create(
        **create_kwargs(
            seeded_factory,
            amount=Decimal("50.50"),
            note="打车",
            tags="travel",
            date=date(2026, 9, 5),
        )
    )


def _notes(records) -> list[str]:
    return [r.note for r in records]


def test_search_by_note(seeded_factory, transaction_service):
    _seed_search_data(seeded_factory, transaction_service)
    assert _notes(transaction_service.search("房租")) == ["九月房租"]
    assert _notes(transaction_service.search("午饭")) == ["午饭"]


def test_search_by_channel_name(seeded_factory, transaction_service):
    _seed_search_data(seeded_factory, transaction_service)
    assert len(transaction_service.search("Salary")) == 3
    assert len(transaction_service.search("salary")) == 3  # 大小写不敏感


def test_search_by_account_name(seeded_factory, transaction_service):
    _seed_search_data(seeded_factory, transaction_service)
    assert len(transaction_service.search("Bank")) == 3


def test_search_by_category_name(seeded_factory, transaction_service):
    _seed_search_data(seeded_factory, transaction_service)
    assert len(transaction_service.search("餐饮")) == 3
    assert transaction_service.search("Other") == []


def test_search_by_tags(seeded_factory, transaction_service):
    _seed_search_data(seeded_factory, transaction_service)
    assert _notes(transaction_service.search("travel")) == ["打车"]
    assert _notes(transaction_service.search("food")) == ["午饭"]  # 标签 food,lunch 部分匹配


def test_search_by_amount_exact(seeded_factory, transaction_service):
    """金额精确匹配：50 命中 ¥50.00，不会误匹配 ¥50.50。"""
    _seed_search_data(seeded_factory, transaction_service)
    assert _notes(transaction_service.search("50")) == ["午饭"]
    assert _notes(transaction_service.search("50.00")) == ["午饭"]
    assert _notes(transaction_service.search("50.5")) == ["打车"]
    assert _notes(transaction_service.search("1234.56")) == ["九月房租"]


def test_search_amount_is_not_partial(seeded_factory, transaction_service):
    _seed_search_data(seeded_factory, transaction_service)
    assert _notes(transaction_service.search("50")) == ["午饭"]  # 不含 ¥50.50


def test_search_keyword_trimmed(seeded_factory, transaction_service):
    _seed_search_data(seeded_factory, transaction_service)
    assert _notes(transaction_service.search("  午饭  ")) == ["午饭"]


def test_search_empty_returns_all(seeded_factory, transaction_service):
    _seed_search_data(seeded_factory, transaction_service)
    assert len(transaction_service.search("")) == 3
    assert len(transaction_service.search("   ")) == 3


def test_search_no_match(seeded_factory, transaction_service):
    _seed_search_data(seeded_factory, transaction_service)
    assert transaction_service.search("不存在的关键词") == []


def test_search_text_with_dash_not_amount(seeded_factory, transaction_service):
    """含 - 的日期文本不按金额解析，走文本模糊匹配。"""
    _seed_search_data(seeded_factory, transaction_service)
    assert transaction_service.search("2026-09-01") == []


def test_search_numeric_keyword_also_matches_text(seeded_factory, transaction_service):
    """数字关键词同时参与文本匹配：备注含 1234 也能搜到。"""
    transaction_service.create(
        **create_kwargs(seeded_factory, amount=Decimal("10.00"), note="订单 1234")
    )
    assert _notes(transaction_service.search("1234")) == ["订单 1234"]


def test_search_escapes_like_wildcards(seeded_factory, transaction_service):
    """% / _ 按字面搜索，不再被当作 LIKE 通配符。"""
    transaction_service.create(**create_kwargs(seeded_factory, note="订单100号"))
    assert _notes(transaction_service.search("100")) == ["订单100号"]
    assert transaction_service.search("100%") == []
    assert transaction_service.search("_") == []
