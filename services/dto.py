"""服务层向 UI 返回的简单数据结构（DTO）：UI 不直接接触 ORM 对象。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class IdName:
    """下拉框等场景使用的「id + 名称」。"""

    id: int
    name: str


@dataclass(frozen=True)
class TransactionRecord:
    """交易记录视图：包含外键 id 与显示名称。

    引用可空：渠道/账户/分类被删除后 id 与名称为 None（软外键，历史交易不受影响）。
    """

    id: int
    type: str
    amount: Decimal
    date: date
    channel_id: int | None
    account_id: int | None
    category_id: int | None
    note: str
    tags: str
    channel_name: str | None
    account_name: str | None
    category_name: str | None


@dataclass(frozen=True)
class ChannelInfo:
    """渠道管理视图（含每月固定金额与交易数）。"""

    id: int
    name: str
    description: str
    monthly_amount: Decimal
    is_active: bool
    transaction_count: int


@dataclass(frozen=True)
class AccountInfo:
    """账户管理视图（含初始余额与交易数）。"""

    id: int
    name: str
    description: str
    initial_balance: Decimal
    is_active: bool
    transaction_count: int


@dataclass(frozen=True)
class CategoryInfo:
    """分类管理视图（含类型与交易数）。"""

    id: int
    name: str
    type: str
    description: str
    is_active: bool
    transaction_count: int


@dataclass(frozen=True)
class ChannelStatistics:
    """渠道统计视图（月度 Dashboard 用）。

    balance_percent 为月度口径（用户确认）：
    (本月收入 - 本月支出) / 本月收入，每月重新计算；None = N/A（本月收入为 0）。
    cumulative_income/expense/balance 仍为累计口径（需求 §18）。
    """

    channel_id: int
    channel_name: str
    is_active: bool
    monthly_amount: Decimal
    month_income: Decimal
    month_expense: Decimal
    cumulative_income: Decimal
    cumulative_expense: Decimal
    balance: Decimal
    balance_percent: Decimal | None  # None = N/A（本月收入为 0）


@dataclass(frozen=True)
class AccountBalance:
    """账户余额视图（截至选定月末，需求 §22/§25）。"""

    account_id: int
    account_name: str
    is_active: bool
    initial_balance: Decimal
    balance: Decimal


@dataclass(frozen=True)
class MonthStatistics:
    """月度统计总视图。"""

    year: int
    month: int
    month_income: Decimal
    month_expense: Decimal
    month_net: Decimal
    channels: list[ChannelStatistics]
    accounts: list[AccountBalance]


@dataclass(frozen=True)
class TransactionPage:
    """分页查询结果（历史记录翻页）。"""

    records: list[TransactionRecord]
    total: int
    page: int
    page_size: int
    pages: int


@dataclass
class ImportResult:
    """导入结果。errors 非空表示导入失败（未写入任何数据，需求 §32）；
    warnings 不阻断导入（如引用已停用实体，用户确认的放宽规则）。"""

    imported: int = 0
    skipped_duplicates: int = 0
    created_channels: int = 0
    created_accounts: int = 0
    created_categories: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def summary(self) -> str:
        """面向用户的中文汇总。"""
        parts = [f"新增交易 {self.imported} 笔", f"跳过重复 {self.skipped_duplicates} 笔"]
        if self.created_channels:
            parts.append(f"新增渠道 {self.created_channels} 个")
        if self.created_accounts:
            parts.append(f"新增账户 {self.created_accounts} 个")
        if self.created_categories:
            parts.append(f"新增分类 {self.created_categories} 个")
        if self.warnings:
            parts.append(f"警告 {len(self.warnings)} 条")
        return "，".join(parts)
