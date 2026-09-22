"""SQLAlchemy ORM 数据模型（需求 §4）。

核心实体（严格区分、绝不合并）：
- Channel    渠道：钱来自哪里 / 资金属于哪个来源（如 Salary、Bonus）
- Account    实际账户：钱实际存在哪里（如 Bank、Alipay）
- Category   分类：这笔收入/支出属于什么类别（如 餐饮、Salary）

Transaction 统一记录收入与支出（type = income / expense）。

金额存储策略（重要）：
SQLite 没有真正的 DECIMAL 类型，直接用 float 会出现 0.1 + 0.2 != 0.3 的精度问题。
因此所有金额通过 Amount TypeDecorator 以「分」为单位用整数存入数据库
（例：¥1234.56 -> 存 123456 -> 读回 Decimal("1234.56")），
Python 层统一使用 decimal.Decimal 运算，保证财务计算精确。
"""

from __future__ import annotations

import enum
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator


def _local_now() -> datetime:
    """系统本地时间（不带时区）。本地个人应用不做 UTC 转换（需求 §41）。"""
    return datetime.now()


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""


class Amount(TypeDecorator):
    """金额列类型：Python 侧 Decimal，数据库侧整数「分」。

    例：Decimal("1234.56") -> 存 123456 -> 读回 Decimal("1234.56")。
    这样 0.1 + 0.2 恒等于 0.3，且 SQL 的 SUM 也是精确整数运算。
    """

    impl = Integer
    cache_ok = True

    _SCALE = Decimal(100)

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        amount = value if isinstance(value, Decimal) else Decimal(str(value))
        return int((amount * self._SCALE).quantize(Decimal(1), rounding=ROUND_HALF_UP))

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return Decimal(value) / self._SCALE


class Channel(Base):
    """渠道：钱来自哪里 / 这部分资金属于哪个来源。

    与 Account、Category 是相互独立的数据实体。
    停用（is_active=False）后历史交易不受影响（需求 §4.1）。
    monthly_amount：每月固定金额（如固定工资 3000），Dashboard 统计自动计入，
    不产生真实交易（用户确认的功能）。
    """

    __tablename__ = "channels"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    monthly_amount: Mapped[Decimal] = mapped_column(Amount, nullable=False, default=Decimal("0"))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # 自定义排序
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_local_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_local_now, onupdate=_local_now
    )

    transactions: Mapped[list["Transaction"]] = relationship(back_populates="channel")

    def __repr__(self) -> str:
        return f"<Channel id={self.id} name={self.name!r}>"


class Account(Base):
    """实际账户：钱实际存在哪里（如 Bank、Alipay、Cash）。

    当前余额 = initial_balance + 累计收入 - 累计支出（由统计服务计算，需求 §4.2/§27）。
    """

    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    initial_balance: Mapped[Decimal] = mapped_column(Amount, nullable=False, default=Decimal("0"))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # 自定义排序
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_local_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_local_now, onupdate=_local_now
    )

    transactions: Mapped[list["Transaction"]] = relationship(back_populates="account")

    def __repr__(self) -> str:
        return f"<Account id={self.id} name={self.name!r}>"


class CategoryType(str, enum.Enum):
    """分类类型：收入 / 支出（逻辑隔离）。"""

    INCOME = "income"
    EXPENSE = "expense"


class Category(Base):
    """分类：这笔收入/支出属于什么类别。

    收入分类与支出分类通过 type 字段逻辑隔离；
    同名的收入分类与支出分类（如两边都有 Other）允许并存、互不冲突。
    """

    __tablename__ = "categories"
    __table_args__ = (
        UniqueConstraint("name", "type", name="uq_categories_name_type"),
        CheckConstraint("type IN ('income', 'expense')", name="ck_categories_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    type: Mapped[str] = mapped_column(String(10), nullable=False)  # income / expense
    description: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # 自定义排序
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_local_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_local_now, onupdate=_local_now
    )

    transactions: Mapped[list["Transaction"]] = relationship(back_populates="category")

    def __repr__(self) -> str:
        return f"<Category id={self.id} name={self.name!r} type={self.type!r}>"


class Transaction(Base):
    """交易：收入与支出统一记录，type 区分（需求 §4.4）。

    金额规则：Decimal 逻辑、必须 > 0（数据库 CheckConstraint 兜底）。

    软外键原则（用户确认的核心规则）：数据库没有硬性外键约束——
    channel / account / category 引用可空 + ON DELETE SET NULL。
    渠道/账户/分类被删除时，历史交易不受影响、不丢失，引用置空后界面显示「已删除」。
    新建交易时渠道/账户/分类仍为必填（业务层校验）；
    用户未选分类时由业务层自动映射为 Other（需求 §4.5）。
    """

    __tablename__ = "transactions"
    __table_args__ = (
        CheckConstraint("type IN ('income', 'expense')", name="ck_transactions_type"),
        CheckConstraint("amount > 0", name="ck_transactions_amount_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(String(10), nullable=False)  # income / expense
    amount: Mapped[Decimal] = mapped_column(Amount, nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    channel_id: Mapped[int | None] = mapped_column(
        ForeignKey("channels.id", ondelete="SET NULL"), nullable=True, index=True
    )
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"), nullable=True, index=True
    )

    note: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    tags: Mapped[str] = mapped_column(String(200), nullable=False, default="")

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_local_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_local_now, onupdate=_local_now
    )

    channel: Mapped["Channel"] = relationship(back_populates="transactions")
    account: Mapped["Account"] = relationship(back_populates="transactions")
    category: Mapped["Category"] = relationship(back_populates="transactions")

    def __repr__(self) -> str:
        return f"<Transaction id={self.id} type={self.type!r} amount={self.amount}>"


class Setting(Base):
    """简单键值设置表（例如备份保留天数 backup_retention_days，需求 §34/§47）。"""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    value: Mapped[str] = mapped_column(String(200), nullable=False, default="")

    def __repr__(self) -> str:
        return f"<Setting key={self.key!r} value={self.value!r}>"
