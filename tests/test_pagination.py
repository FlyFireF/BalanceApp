"""测试历史记录分页查询（翻页功能）。"""

from __future__ import annotations

from decimal import Decimal

from helpers import create_kwargs


def _seed_many(seeded_factory, transaction_service, count: int = 25) -> None:
    for i in range(count):
        transaction_service.create(
            **create_kwargs(seeded_factory, amount=Decimal(f"{i + 1}.00"), note=f"n{i}")
        )


def test_paged_total_pages_and_page_size(seeded_factory, transaction_service):
    _seed_many(seeded_factory, transaction_service, 25)

    page = transaction_service.list_transactions_page(page=1, page_size=10)
    assert page.total == 25
    assert page.pages == 3
    assert page.page_size == 10
    assert len(page.records) == 10

    last = transaction_service.list_transactions_page(page=3, page_size=10)
    assert len(last.records) == 5


def test_paged_order_date_desc_id_desc(seeded_factory, transaction_service):
    _seed_many(seeded_factory, transaction_service, 25)

    page = transaction_service.list_transactions_page(page=1, page_size=50)
    notes = [r.note for r in page.records]
    assert notes == [f"n{i}" for i in range(24, -1, -1)]  # 日期相同 → id 倒序


def test_paged_keyword_filters_total(seeded_factory, transaction_service):
    _seed_many(seeded_factory, transaction_service, 25)

    page = transaction_service.list_transactions_page(keyword="n1", page=1, page_size=50)
    assert page.total == 11  # n1、n10~n19
    assert len(page.records) == 11


def test_paged_beyond_range_returns_empty(seeded_factory, transaction_service):
    _seed_many(seeded_factory, transaction_service, 25)

    page = transaction_service.list_transactions_page(page=99, page_size=10)
    assert page.records == []
    assert page.pages == 3
    assert page.page == 99  # 调用方负责回退


def test_paged_clamps_page_and_size(seeded_factory, transaction_service):
    _seed_many(seeded_factory, transaction_service, 5)

    page = transaction_service.list_transactions_page(page=0, page_size=0)
    assert page.page == 1
    assert page.page_size == 1  # 下限 1
    assert page.total == 5


def test_paged_empty_database(transaction_service):
    page = transaction_service.list_transactions_page()
    assert page.total == 0
    assert page.pages == 1
    assert page.records == []
