"""Transaction 表的数据访问（Repository 层）。"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session, selectinload

from database.models import Account, Category, Channel, Transaction


def _keyword_conditions(keyword: str | None, amount: Decimal | None) -> list:
    """关键词搜索条件：LIKE 通配符 % / _ 已转义（按字面搜索）；金额精确匹配。

    所有值经 SQLAlchemy 参数化绑定（无字符串拼接 SQL，天然防注入）。
    """
    conditions = []
    if keyword:
        escaped = keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        conditions.extend(
            [
                Transaction.note.like(pattern, escape="\\"),
                Transaction.tags.like(pattern, escape="\\"),
                Channel.name.like(pattern, escape="\\"),
                Account.name.like(pattern, escape="\\"),
                Category.name.like(pattern, escape="\\"),
            ]
        )
    if amount is not None:
        conditions.append(Transaction.amount == amount)
    return conditions


def _with_references(stmt):
    """outerjoin 渠道/账户/分类：引用已删除（软外键置空）的交易不丢失。"""
    return stmt.outerjoin(Transaction.channel).outerjoin(Transaction.account).outerjoin(Transaction.category)


def _filter_conditions(filters: dict) -> list:
    """结构化筛选条件（历史记录筛选）：类型 / 渠道 / 账户 / 分类 / 日期范围。"""
    conditions = []
    if filters.get("type") in ("income", "expense"):
        conditions.append(Transaction.type == filters["type"])
    for key, column in (
        ("channel_id", Transaction.channel_id),
        ("account_id", Transaction.account_id),
        ("category_id", Transaction.category_id),
    ):
        if filters.get(key) is not None:
            conditions.append(column == filters[key])
    if filters.get("date_from") is not None:
        conditions.append(Transaction.date >= filters["date_from"])
    if filters.get("date_to") is not None:
        conditions.append(Transaction.date <= filters["date_to"])
    return conditions


def _sort_columns(sort: list[tuple[str, str]]) -> list:
    """多级排序表达式。规则：
    - 类型升序 = 收入在前（CASE：income=0、expense=1）；
    - 按名称排序（渠道/账户/分类）时，引用已删除（NULL）恒排最后
      （tuple_：IS NULL 恒升序，方向只作用于名称列）；
    - 末尾附加 id 倒序，保证同值记录顺序稳定。
    """
    columns = []
    for field, direction in sort:
        desc = direction == "desc"
        if field == "date":
            columns.append(Transaction.date.desc() if desc else Transaction.date.asc())
        elif field == "amount":
            columns.append(Transaction.amount.desc() if desc else Transaction.amount.asc())
        elif field == "type":
            column = case((Transaction.type == "income", 0), else_=1)
            columns.append(column.desc() if desc else column.asc())
        elif field == "channel":
            # SQLite 不支持元组排序语法：拆成两列，IS NULL 恒升序使 NULL 排最后
            columns.append(Channel.name.is_(None).asc())
            columns.append(Channel.name.desc() if desc else Channel.name.asc())
        elif field == "account":
            columns.append(Account.name.is_(None).asc())
            columns.append(Account.name.desc() if desc else Account.name.asc())
        elif field == "category":
            columns.append(Category.name.is_(None).asc())
            columns.append(Category.name.desc() if desc else Category.name.asc())
    columns.append(Transaction.id.desc())
    return columns


class TransactionRepository:
    """交易数据访问：UI 不直接使用，只经由 TransactionService 调用。"""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, transaction: Transaction) -> Transaction:
        """新增交易（flush 以获得 id）。"""
        self._session.add(transaction)
        self._session.flush()
        return transaction

    def get(self, transaction_id: int) -> Transaction | None:
        """按 id 查询。"""
        return self._session.get(Transaction, transaction_id)

    def list_all(self) -> list[Transaction]:
        """全部交易（按日期倒序、同日按 id 倒序），预加载渠道/账户/分类避免 N+1。"""
        stmt = (
            select(Transaction)
            .options(
                selectinload(Transaction.channel),
                selectinload(Transaction.account),
                selectinload(Transaction.category),
            )
            .order_by(Transaction.date.desc(), Transaction.id.desc())
        )
        return list(self._session.scalars(stmt))

    def list_up_to(self, end_date: date) -> list[Transaction]:
        """日期 <= end_date 的全部交易（预加载渠道/账户，月度统计用）。"""
        stmt = (
            select(Transaction)
            .where(Transaction.date <= end_date)
            .options(
                selectinload(Transaction.channel),
                selectinload(Transaction.account),
            )
            .order_by(Transaction.date, Transaction.id)
        )
        return list(self._session.scalars(stmt))

    def search(self, keyword: str, amount: Decimal | None) -> list[Transaction]:
        """按关键词搜索（需求 §13）：备注/标签/渠道名/账户名/分类名模糊匹配，
        金额精确匹配（传「元」，由 Amount 列类型自动换算成「分」比较）。
        按日期倒序返回。"""
        conditions = _keyword_conditions(keyword, amount)
        stmt = _with_references(select(Transaction))
        if conditions:
            stmt = stmt.where(or_(*conditions))
        stmt = (
            stmt.options(
                selectinload(Transaction.channel),
                selectinload(Transaction.account),
                selectinload(Transaction.category),
            )
            .order_by(Transaction.date.desc(), Transaction.id.desc())
        )
        return list(self._session.scalars(stmt))

    def list_paged(
        self,
        *,
        keyword: str | None = None,
        amount: Decimal | None = None,
        filters: dict | None = None,
        sort: list | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[Transaction], int]:
        """分页查询（历史记录翻页 + 筛选 + 多级排序）：返回 (本页记录, 总条数)。

        关键词条件与 search 一致；排序默认按日期倒序。
        """
        # 关键词条件组内为 OR（任一字段命中），筛选条件之间为 AND（全部生效）
        keyword_conditions = _keyword_conditions(keyword, amount)
        filter_conditions = _filter_conditions(filters or {})
        order = _sort_columns(sort) if sort else _sort_columns([("date", "desc")])
        stmt = _with_references(select(Transaction))
        count_stmt = _with_references(select(func.count()).select_from(Transaction))
        if keyword_conditions:
            stmt = stmt.where(or_(*keyword_conditions))
            count_stmt = count_stmt.where(or_(*keyword_conditions))
        if filter_conditions:
            stmt = stmt.where(*filter_conditions)
            count_stmt = count_stmt.where(*filter_conditions)
        stmt = (
            stmt.options(
                selectinload(Transaction.channel),
                selectinload(Transaction.account),
                selectinload(Transaction.category),
            )
            .order_by(*order)
            .limit(limit)
            .offset(offset)
        )
        records = list(self._session.scalars(stmt))
        total = self._session.scalar(count_stmt)
        return records, int(total)

    def delete(self, transaction: Transaction) -> None:
        """删除交易（调用方负责二次确认，需求 §8）。"""
        self._session.delete(transaction)
        self._session.flush()
