"""默认数据（种子数据）：首次启动时自动写入（需求 §43）。

幂等规则：只添加「不存在的」实体，绝不修改或重建已有实体。
因此用户停用/改名的默认实体不会被重新激活或还原。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import Account, Category, CategoryType, Channel, Setting

# 默认渠道（需求 §4.1）
DEFAULT_CHANNELS = {
    "Salary": "工资收入",
    "Bonus": "奖金",
    "Investments": "投资收益",
    "Freelance": "自由职业收入",
    "Other": "其他渠道",
}

# 默认账户（需求 §4.2 示例）
DEFAULT_ACCOUNTS = {
    "Bank": "银行账户",
    "Alipay": "支付宝",
    "WeChat": "微信支付",
    "Cash": "现金",
}

# 默认收入分类（需求 §26）
DEFAULT_INCOME_CATEGORIES = ["Salary", "Bonus", "Investment Return", "Freelance", "Other"]

# 默认支出分类（需求 §26）
DEFAULT_EXPENSE_CATEGORIES = ["餐饮", "出行", "购物", "娱乐", "房租", "学习", "医疗", "日用品", "Other"]

# 默认设置
DEFAULT_SETTINGS = {
    "backup_retention_days": "30",
    "theme": "system",  # light / dark / system（跟随系统）
}


def seed_defaults(session: Session) -> None:
    """幂等地写入默认渠道 / 账户 / 分类 / 设置。"""
    for name, description in DEFAULT_CHANNELS.items():
        if session.scalar(select(Channel).where(Channel.name == name)) is None:
            session.add(Channel(name=name, description=description))

    for name, description in DEFAULT_ACCOUNTS.items():
        if session.scalar(select(Account).where(Account.name == name)) is None:
            session.add(Account(name=name, description=description))

    for name in DEFAULT_INCOME_CATEGORIES:
        if not session.scalar(
            select(Category).where(
                Category.name == name, Category.type == CategoryType.INCOME.value
            )
        ):
            session.add(Category(name=name, type=CategoryType.INCOME.value))

    for name in DEFAULT_EXPENSE_CATEGORIES:
        if not session.scalar(
            select(Category).where(
                Category.name == name, Category.type == CategoryType.EXPENSE.value
            )
        ):
            session.add(Category(name=name, type=CategoryType.EXPENSE.value))

    for key, value in DEFAULT_SETTINGS.items():
        if session.get(Setting, key) is None:
            session.add(Setting(key=key, value=value))

    session.flush()
