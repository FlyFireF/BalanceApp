"""测试金额工具：解析与格式化（此前只被间接覆盖，补直接测试）。"""

from __future__ import annotations

from decimal import Decimal

import pytest

from utils.currency import format_money, parse_amount


# ---------- parse_amount ----------

def test_parse_amount_plain():
    assert parse_amount("1234.56") == Decimal("1234.56")


def test_parse_amount_with_currency_symbols_and_commas():
    assert parse_amount("¥1,234.56") == Decimal("1234.56")
    assert parse_amount("￥ 1，234.5 ") == Decimal("1234.5")


def test_parse_amount_integer():
    assert parse_amount("88") == Decimal("88")


def test_parse_amount_strips_commas_anywhere():
    """用户确认规则：逗号一律舍去（x,xxx.xx / xx,xx.xx 均按数字拼接）。"""
    assert parse_amount("1,234.56") == Decimal("1234.56")
    assert parse_amount("12,34") == Decimal("1234")
    assert parse_amount("1,2,3") == Decimal("123")


def test_parse_amount_empty_raises():
    with pytest.raises(ValueError, match="不能为空"):
        parse_amount("")


def test_parse_amount_none_raises():
    with pytest.raises(ValueError, match="不能为空"):
        parse_amount(None)


def test_parse_amount_invalid_raises():
    with pytest.raises(ValueError, match="不是有效数字"):
        parse_amount("abc")


def test_parse_amount_nan_raises():
    with pytest.raises(ValueError, match="不是有效数字"):
        parse_amount("NaN")


# ---------- format_money ----------

def test_format_money_basic():
    assert format_money(Decimal("1234.56")) == "¥1,234.56"
    assert format_money(Decimal("1234.5")) == "¥1,234.50"
    assert format_money(Decimal("0")) == "¥0.00"


def test_format_money_negative():
    assert format_money(Decimal("-1000.5")) == "-¥1,000.50"


def test_format_money_int_and_str():
    assert format_money(88) == "¥88.00"
    assert format_money("66.6") == "¥66.60"


def test_format_money_none_shows_dash():
    """缺失金额显示「—」，不伪装成 0（中间检查第 2 项修复）。"""
    assert format_money(None) == "—"
