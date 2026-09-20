"""交易（收入/支出）业务服务：创建、编辑、删除、查询（需求 §6/§7/§8）。

校验规则（需求 §4.5）：
- 金额：Decimal、有限数字、> 0；超出两位小数时四舍五入到分（与存储策略一致）；
- 日期：必须是 date（拒绝 datetime），不做时区转换（需求 §41）；
- 渠道 / 账户 / 分类必须存在且处于启用状态；
- 分类类型必须与交易类型一致；未选分类自动映射为对应类型的 Other；
- 备注 / 标签自动去除首尾空白，并有长度限制。

删除为硬删除；二次确认由 UI 层负责（需求 §8）。
"""

from __future__ import annotations

import datetime
import logging
import math
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from database import database
from database.models import Account, Category, CategoryType, Channel, Transaction
from database.repositories.transaction_repository import TransactionRepository
from services.dto import TransactionPage, TransactionRecord
from services.exceptions import NotFoundError, ValidationError
from utils.currency import parse_amount

logger = logging.getLogger(__name__)

_CENT = Decimal("0.01")

TRANSACTION_TYPES = (CategoryType.INCOME.value, CategoryType.EXPENSE.value)

_MAX_NOTE_LENGTH = 500
_MAX_TAGS_LENGTH = 200

_SORT_FIELDS = ("date", "type", "amount", "channel", "account", "category")
_SORT_DIRECTIONS = ("asc", "desc")
_FILTER_KEYS = ("type", "channel_id", "account_id", "category_id", "date_from", "date_to")


class TransactionService:
    """交易业务服务：UI 只经由本服务操作交易数据。"""

    def __init__(self, session_factory: sessionmaker | None = None) -> None:
        """session_factory 为空时使用全局会话工厂；测试注入临时库的工厂。"""
        self._session_factory = session_factory or database.get_session_factory()

    # ---------- 创建 ----------

    def create(
        self,
        *,
        type: str,
        amount: Decimal,
        date: datetime.date,
        channel_id: int,
        account_id: int,
        category_id: int | None = None,
        note: str = "",
        tags: str = "",
    ) -> int:
        """创建一笔收入/支出交易，返回新交易 id。

        category_id 为 None 时自动映射为对应类型的 Other 分类（需求 §4.5）。

        Raises:
            ValidationError: 任一字段不合法（中文提示）。
        """
        with database.session_scope(self._session_factory) as session:
            fields = self._prepare_fields(
                session,
                type=type,
                amount=amount,
                date=date,
                channel_id=channel_id,
                account_id=account_id,
                category_id=category_id,
                note=note,
                tags=tags,
            )
            transaction = TransactionRepository(session).add(Transaction(**fields))
            transaction_id = transaction.id
        logger.info("创建交易 #%d（%s，%s）", transaction_id, fields["type"], fields["date"])
        return transaction_id

    # ---------- 更新 ----------

    def update(
        self,
        transaction_id: int,
        *,
        type: str,
        amount: Decimal,
        date: datetime.date,
        channel_id: int | None,
        account_id: int | None,
        category_id: int | None = None,
        note: str = "",
        tags: str = "",
    ) -> None:
        """全量更新一笔交易（编辑弹窗提交全部字段）。

        放宽规则（用户确认）：引用的渠道/账户/分类保持不变时，允许其已停用
        甚至已被删除（引用为 None）——历史交易随时可编辑（需求 §39）；
        只有新建交易或更换引用时才要求实体存在且启用。

        Raises:
            NotFoundError: 交易不存在。
            ValidationError: 任一字段不合法（中文提示）。
        """
        with database.session_scope(self._session_factory) as session:
            transaction = session.get(Transaction, transaction_id)
            if transaction is None:
                raise NotFoundError(f"交易 #{transaction_id} 不存在")
            fields = self._prepare_fields(
                session,
                type=type,
                amount=amount,
                date=date,
                channel_id=channel_id,
                account_id=account_id,
                category_id=category_id,
                note=note,
                tags=tags,
                current=transaction,
            )
            for key, value in fields.items():
                setattr(transaction, key, value)
        logger.info("更新交易 #%d", transaction_id)

    # ---------- 删除 ----------

    def delete(self, transaction_id: int) -> None:
        """删除一笔交易（硬删除；二次确认由 UI 层负责）。

        Raises:
            NotFoundError: 交易不存在。
        """
        with database.session_scope(self._session_factory) as session:
            repo = TransactionRepository(session)
            transaction = repo.get(transaction_id)
            if transaction is None:
                raise NotFoundError(f"交易 #{transaction_id} 不存在")
            repo.delete(transaction)
        logger.info("删除交易 #%d", transaction_id)

    # ---------- 查询 ----------

    def list_transactions(self) -> list[TransactionRecord]:
        """全部交易（日期倒序、同日按 id 倒序）。"""
        with database.session_scope(self._session_factory) as session:
            transactions = TransactionRepository(session).list_all()
            return [self._to_record(t) for t in transactions]

    def get(self, transaction_id: int) -> TransactionRecord | None:
        """按 id 查询；不存在返回 None。"""
        with database.session_scope(self._session_factory) as session:
            transaction = TransactionRepository(session).get(transaction_id)
            return self._to_record(transaction) if transaction else None

    def list_transactions_page(
        self,
        *,
        keyword: str | None = None,
        filters: dict | None = None,
        sort: list | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> TransactionPage:
        """分页查询交易（翻页 + 筛选 + 多级排序）。

        - keyword：搜索词（空 = 全部）；
        - filters：{"type"/"channel_id"/"account_id"/"category_id"/"date_from"/"date_to"}；
        - sort：[(字段, "asc"|"desc"), ...] 最多 3 级，空则默认日期降序；
          类型升序 = 收入在前。

        Raises:
            ValidationError: 筛选/排序参数不合法。
        """
        keyword = (keyword or "").strip() or None
        page = max(1, int(page))
        page_size = max(1, min(200, int(page_size)))
        clean_filters = self._clean_filters(filters or {})
        clean_sort = self._clean_sort(sort)
        if keyword:
            try:
                parsed = parse_amount(keyword)
            except ValueError:
                amount = None
            else:
                amount = parsed.quantize(_CENT, rounding=ROUND_HALF_UP)
        else:
            amount = None
        with database.session_scope(self._session_factory) as session:
            records, total = TransactionRepository(session).list_paged(
                keyword=keyword,
                amount=amount,
                filters=clean_filters,
                sort=clean_sort,
                offset=(page - 1) * page_size,
                limit=page_size,
            )
        pages = max(1, math.ceil(total / page_size))
        return TransactionPage(
            records=[self._to_record(t) for t in records],
            total=total,
            page=page,
            page_size=page_size,
            pages=pages,
        )

    @staticmethod
    def _clean_filters(filters: dict) -> dict:
        """筛选参数校验：只保留已知键，校验类型与日期。"""
        result: dict = {}
        for key in _FILTER_KEYS:
            value = filters.get(key)
            if value is None:
                continue
            if key == "type" and value not in TRANSACTION_TYPES:
                raise ValidationError("筛选类型无效")
            if key in ("date_from", "date_to") and not isinstance(value, datetime.date):
                raise ValidationError("筛选日期无效")
            result[key] = value
        return result

    @staticmethod
    def _clean_sort(sort) -> list:
        """排序参数校验：字段与方向必须在白名单内；空则默认日期降序。"""
        normalized = []
        for item in sort or ():
            if not isinstance(item, (tuple, list)) or len(item) != 2:
                raise ValidationError("排序参数无效")
            field, direction = item
            if field not in _SORT_FIELDS or direction not in _SORT_DIRECTIONS:
                raise ValidationError(f"排序参数无效：{field} {direction}")
            normalized.append((field, direction))
        return normalized or [("date", "desc")]

    def search(self, keyword: str) -> list[TransactionRecord]:
        """按关键词搜索交易（需求 §13）：金额 / 备注 / 标签 / 渠道 / 账户 / 分类。

        - 空关键词返回全部交易；
        - 金额按「分」精确匹配：输入 50 或 50.00 都命中 ¥50.00，
          不会把 50 误匹配成 ¥50.50；
        - 数字关键词同时参与文本模糊匹配（如备注包含 1234 也可搜到）。
        """
        keyword = (keyword or "").strip()
        if not keyword:
            return self.list_transactions()
        try:
            parsed = parse_amount(keyword)
        except ValueError:
            amount = None
        else:
            amount = parsed.quantize(_CENT, rounding=ROUND_HALF_UP)
        with database.session_scope(self._session_factory) as session:
            transactions = TransactionRepository(session).search(keyword, amount)
            return [self._to_record(t) for t in transactions]

    # ---------- 内部 ----------

    def _prepare_fields(
        self,
        session,
        *,
        type: str,
        amount: Decimal,
        date: datetime.date,
        channel_id: int | None,
        account_id: int | None,
        category_id: int | None,
        note: str,
        tags: str,
        current: Transaction | None = None,
    ) -> dict:
        """校验并规范化全部字段，返回可直接写入 Transaction 的 dict。

        current 为编辑中的原交易：引用的实体保持不变时允许其已停用/已删除
        （软外键原则）；新建（current=None）或更换引用时要求实体存在且启用。
        """
        if type not in TRANSACTION_TYPES:
            raise ValidationError("交易类型无效")

        if not isinstance(amount, Decimal) or not amount.is_finite():
            raise ValidationError("金额不是有效数字")
        amount = amount.quantize(_CENT, rounding=ROUND_HALF_UP)
        if amount <= 0:
            raise ValidationError("金额必须大于 0")

        # datetime 是 date 的子类，需显式拒绝，避免日期带时间部分
        if isinstance(date, datetime.datetime) or not isinstance(date, datetime.date):
            raise ValidationError("日期无效")

        channel = session.get(Channel, channel_id) if channel_id is not None else None
        if (channel is None or not channel.is_active) and not (
            current is not None and channel_id == current.channel_id
        ):
            if channel_id is None:
                raise ValidationError("请选择渠道")
            raise ValidationError("渠道不存在或已停用")

        account = session.get(Account, account_id) if account_id is not None else None
        if (account is None or not account.is_active) and not (
            current is not None and account_id == current.account_id
        ):
            if account_id is None:
                raise ValidationError("请选择账户")
            raise ValidationError("账户不存在或已停用")

        if category_id is not None:
            category = session.get(Category, category_id)
            if (category is None or not category.is_active) and not (
                current is not None and category_id == current.category_id
            ):
                raise ValidationError("分类不存在或已停用")
            if category is not None and category.type != type:
                raise ValidationError("分类类型与交易类型不匹配")
        elif current is not None and current.category_id is None:
            category = None  # 分类已被删除，引用保持不变（软外键）
        else:
            # 需求 §4.5：未选分类自动映射为 Other
            category = session.scalar(
                select(Category).where(
                    Category.name == "Other",
                    Category.type == type,
                    Category.is_active.is_(True),
                )
            )
            if category is None:
                raise ValidationError("缺少 Other 分类，请先在分类管理中恢复")
            category_id = category.id

        note = (note or "").strip()
        tags = (tags or "").strip()
        if len(note) > _MAX_NOTE_LENGTH:
            raise ValidationError(f"备注过长（最多 {_MAX_NOTE_LENGTH} 个字符）")
        if len(tags) > _MAX_TAGS_LENGTH:
            raise ValidationError(f"标签过长（最多 {_MAX_TAGS_LENGTH} 个字符）")

        return {
            "type": type,
            "amount": amount,
            "date": date,
            "channel_id": channel_id,
            "account_id": account_id,
            "category_id": category_id,
            "note": note,
            "tags": tags,
        }

    @staticmethod
    def _to_record(transaction: Transaction) -> TransactionRecord:
        """ORM 对象 -> 视图 DTO（需在会话内调用）。

        引用可能已删除（软外键置空）：id 与名称均为 None，UI 显示「已删除」。
        """
        return TransactionRecord(
            id=transaction.id,
            type=transaction.type,
            amount=transaction.amount,
            date=transaction.date,
            channel_id=transaction.channel_id,
            account_id=transaction.account_id,
            category_id=transaction.category_id,
            note=transaction.note,
            tags=transaction.tags,
            channel_name=transaction.channel.name if transaction.channel else None,
            account_name=transaction.account.name if transaction.account else None,
            category_name=transaction.category.name if transaction.category else None,
        )
