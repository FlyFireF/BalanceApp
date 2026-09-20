"""金额工具：输入解析与显示格式化。

财务应用禁止用 float 做核心金额运算（0.1 + 0.2 != 0.3），
本模块所有金额统一使用 decimal.Decimal。
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

ZERO = Decimal("0")


def parse_amount(text: str) -> Decimal:
    """把用户输入的金额文本解析为 Decimal。

    容忍常见写法：¥ / ￥ 符号、千分位逗号、空格。
    只负责「语法解析」，是否 > 0 由调用方校验。

    Raises:
        ValueError: 文本为空或不是有效数字。
    """
    if text is None:
        raise ValueError("金额不能为空")
    cleaned = (
        str(text)
        .strip()
        .replace("¥", "")
        .replace("￥", "")
        .replace(",", "")
        .replace("，", "")
        .replace(" ", "")
    )
    if not cleaned:
        raise ValueError("金额不能为空")
    try:
        amount = Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError(f"金额不是有效数字: {text!r}") from exc
    if not amount.is_finite():
        raise ValueError(f"金额不是有效数字: {text!r}")
    return amount


def format_money(amount: Decimal | int | str | None) -> str:
    """统一金额显示格式：¥1,234.56（千分位 + 两位小数）。

    None 显示为「—」：缺失值不伪装成 0。
    负号在货币符号前（需求 §20 示例：-¥1000）。
    """
    if amount is None:
        return "—"
    value = Decimal(str(amount))
    sign = "-" if value < 0 else ""
    return f"{sign}¥{abs(value):,.2f}"
