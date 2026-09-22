"""基础数据（渠道/账户/分类）服务：查询 + 管理（需求 §4.1/§4.2/§4.3/§26/§27）。

规则：
- 名称唯一（分类在「类型」内唯一）；
- 停用后不能用于新建交易（TransactionService 校验启用状态），历史交易不受影响；
- 账户初始余额可随时编辑，余额统计基于最新值计算；
- 分类类型不可修改：交易历史依赖分类类型，改类型会破坏统计一致性；
- Other 分类是自动映射目标（需求 §4.5），不允许停用。
"""

from __future__ import annotations

import logging
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from database import database
from database.models import Account, Category, CategoryType, Channel, Transaction
from services.dto import AccountInfo, CategoryInfo, ChannelInfo, IdName
from services.exceptions import NotFoundError, ValidationError

logger = logging.getLogger(__name__)

_TYPE_VALUES = (CategoryType.INCOME.value, CategoryType.EXPENSE.value)

_CENT = Decimal("0.01")

_MAX_NAME_LENGTH = 50
_MAX_DESCRIPTION_LENGTH = 200


def _clean_name(name: str, label: str) -> str:
    """名称：非空、去空白、限长。"""
    name = (name or "").strip()
    if not name:
        raise ValidationError(f"{label}名称不能为空")
    if len(name) > _MAX_NAME_LENGTH:
        raise ValidationError(f"{label}名称过长（最多 {_MAX_NAME_LENGTH} 个字符）")
    return name


def _clean_description(description: str) -> str:
    """描述：去空白、限长（可为空）。"""
    description = (description or "").strip()
    if len(description) > _MAX_DESCRIPTION_LENGTH:
        raise ValidationError(f"描述过长（最多 {_MAX_DESCRIPTION_LENGTH} 个字符）")
    return description


def _clean_balance(amount, label: str) -> Decimal:
    """金额：必须是有限 Decimal，四舍五入到分。"""
    if not isinstance(amount, Decimal) or not amount.is_finite():
        raise ValidationError(f"{label}不是有效数字")
    return amount.quantize(_CENT, rounding=ROUND_HALF_UP)


def _clean_monthly_amount(amount) -> Decimal:
    """每月固定金额：有限 Decimal、四舍五入到分、不能为负。"""
    cleaned = _clean_balance(amount, "每月固定金额")
    if cleaned < 0:
        raise ValidationError("每月固定金额不能为负数")
    return cleaned


class CatalogService:
    """渠道 / 账户 / 分类的查询与管理入口。"""

    def __init__(self, session_factory: sessionmaker | None = None) -> None:
        self._session_factory = session_factory or database.get_session_factory()

    # ================= 渠道 Channel =================

    def list_active_channels(self) -> list[IdName]:
        """所有启用中的渠道（按自定义排序；未排序时按名称）。"""
        with database.session_scope(self._session_factory) as session:
            channels = session.scalars(
                select(Channel)
                .where(Channel.is_active.is_(True))
                .order_by(Channel.sort_order, Channel.name)
            )
            return [IdName(c.id, c.name) for c in channels]

    def list_all_channels(self) -> list[ChannelInfo]:
        """全部渠道（含停用），带每月固定金额与交易数（管理页用）。"""
        with database.session_scope(self._session_factory) as session:
            channels = session.scalars(
                select(Channel).order_by(Channel.sort_order, Channel.name)
            )
            counts = self._transaction_counts(session, Transaction.channel_id)
            return [
                ChannelInfo(
                    id=c.id,
                    name=c.name,
                    description=c.description,
                    monthly_amount=c.monthly_amount,
                    is_active=c.is_active,
                    transaction_count=counts.get(c.id, 0),
                )
                for c in channels
            ]

    def create_channel(
        self, name: str, description: str = "", monthly_amount: Decimal = Decimal("0")
    ) -> int:
        """新增渠道；名称唯一。monthly_amount 为每月固定金额（用户确认的功能）。"""
        name = _clean_name(name, "渠道")
        description = _clean_description(description)
        monthly_amount = _clean_monthly_amount(monthly_amount)
        with database.session_scope(self._session_factory) as session:
            if session.scalar(select(Channel).where(Channel.name == name)):
                raise ValidationError("渠道名称已存在")
            max_order = session.scalar(select(func.max(Channel.sort_order))) or 0
            channel = Channel(
                name=name,
                description=description,
                monthly_amount=monthly_amount,
                sort_order=max_order + 1,  # 新渠道追加到列表末尾
            )
            session.add(channel)
            session.flush()
            channel_id = channel.id
        logger.info("新增渠道 #%d：%s", channel_id, name)
        return channel_id

    def update_channel(
        self,
        channel_id: int,
        name: str,
        description: str = "",
        monthly_amount: Decimal | None = None,
    ) -> None:
        """编辑渠道名称/描述/每月固定金额（monthly_amount 为 None 表示不变）。"""
        name = _clean_name(name, "渠道")
        description = _clean_description(description)
        if monthly_amount is not None:
            monthly_amount = _clean_monthly_amount(monthly_amount)
        with database.session_scope(self._session_factory) as session:
            channel = session.get(Channel, channel_id)
            if channel is None:
                raise NotFoundError(f"渠道 #{channel_id} 不存在")
            duplicate = session.scalar(
                select(Channel).where(Channel.name == name, Channel.id != channel_id)
            )
            if duplicate:
                raise ValidationError("渠道名称已存在")
            channel.name = name
            channel.description = description
            if monthly_amount is not None:
                channel.monthly_amount = monthly_amount
        logger.info("更新渠道 #%d：%s", channel_id, name)

    def set_channel_active(self, channel_id: int, is_active: bool) -> None:
        """启用/停用渠道。停用后不能新建交易；历史交易不受影响（需求 §4.1）。"""
        with database.session_scope(self._session_factory) as session:
            channel = session.get(Channel, channel_id)
            if channel is None:
                raise NotFoundError(f"渠道 #{channel_id} 不存在")
            channel.is_active = is_active
        logger.info("渠道 #%d 状态 -> %s", channel_id, is_active)

    def move_channel(self, channel_id: int, direction: str) -> None:
        """上移/下移渠道（用户反馈：下拉框顺序自定义，解决高频渠道每次重选）。"""
        if direction not in ("up", "down"):
            raise ValidationError("移动方向无效")
        with database.session_scope(self._session_factory) as session:
            channels = session.scalars(
                select(Channel).order_by(Channel.sort_order, Channel.name)
            ).all()
            self._move_in_list(channels, channel_id, direction, "渠道")

    @staticmethod
    def _move_in_list(entities, entity_id: int, direction: str, label: str) -> None:
        """在有序实体列表中上移/下移：归一化排序值后交换相邻两项。边界处不动。"""
        index = next((i for i, e in enumerate(entities) if e.id == entity_id), None)
        if index is None:
            raise NotFoundError(f"{label} #{entity_id} 不存在")
        target = index - 1 if direction == "up" else index + 1
        if target < 0 or target >= len(entities):
            return
        for i, entity in enumerate(entities):
            entity.sort_order = i
        entities[index].sort_order, entities[target].sort_order = (
            entities[target].sort_order,
            entities[index].sort_order,
        )

    def delete_channel(self, channel_id: int) -> None:
        """删除渠道（仅限已停用）。

        历史交易不受影响：软外键将引用置空（ON DELETE SET NULL）。
        二次确认由 UI 层负责。
        """
        with database.session_scope(self._session_factory) as session:
            channel = session.get(Channel, channel_id)
            if channel is None:
                raise NotFoundError(f"渠道 #{channel_id} 不存在")
            if channel.is_active:
                raise ValidationError("只能删除已停用的渠道，请先停用")
            session.delete(channel)
        logger.info("删除渠道 #%d", channel_id)

    # ================= 账户 Account =================

    def list_active_accounts(self) -> list[IdName]:
        """所有启用中的账户（按自定义排序；未排序时按名称）。"""
        with database.session_scope(self._session_factory) as session:
            accounts = session.scalars(
                select(Account)
                .where(Account.is_active.is_(True))
                .order_by(Account.sort_order, Account.name)
            )
            return [IdName(a.id, a.name) for a in accounts]

    def list_all_accounts(self) -> list[AccountInfo]:
        """全部账户（含停用），带交易数（管理页用）。"""
        with database.session_scope(self._session_factory) as session:
            accounts = session.scalars(
                select(Account).order_by(Account.sort_order, Account.name)
            )
            counts = self._transaction_counts(session, Transaction.account_id)
            return [
                AccountInfo(
                    id=a.id,
                    name=a.name,
                    description=a.description,
                    initial_balance=a.initial_balance,
                    is_active=a.is_active,
                    transaction_count=counts.get(a.id, 0),
                )
                for a in accounts
            ]

    def create_account(
        self, name: str, description: str = "", initial_balance: Decimal = Decimal("0")
    ) -> int:
        """新增账户；名称唯一，初始余额四舍五入到分（允许负数，如信用卡）。"""
        name = _clean_name(name, "账户")
        description = _clean_description(description)
        initial_balance = _clean_balance(initial_balance, "初始余额")
        with database.session_scope(self._session_factory) as session:
            if session.scalar(select(Account).where(Account.name == name)):
                raise ValidationError("账户名称已存在")
            max_order = session.scalar(select(func.max(Account.sort_order))) or 0
            account = Account(
                name=name,
                description=description,
                initial_balance=initial_balance,
                sort_order=max_order + 1,  # 新账户追加到列表末尾
            )
            session.add(account)
            session.flush()
            account_id = account.id
        logger.info("新增账户 #%d：%s", account_id, name)
        return account_id

    def update_account(
        self, account_id: int, name: str, description: str = "", initial_balance: Decimal = Decimal("0")
    ) -> None:
        """编辑账户（含初始余额）。修改后账户余额统计自动重新计算（需求 §27）。"""
        name = _clean_name(name, "账户")
        description = _clean_description(description)
        initial_balance = _clean_balance(initial_balance, "初始余额")
        with database.session_scope(self._session_factory) as session:
            account = session.get(Account, account_id)
            if account is None:
                raise NotFoundError(f"账户 #{account_id} 不存在")
            duplicate = session.scalar(
                select(Account).where(Account.name == name, Account.id != account_id)
            )
            if duplicate:
                raise ValidationError("账户名称已存在")
            account.name = name
            account.description = description
            account.initial_balance = initial_balance
        logger.info("更新账户 #%d：%s", account_id, name)

    def set_account_active(self, account_id: int, is_active: bool) -> None:
        """启用/停用账户。停用后不能新建交易；历史数据不丢失（需求 §4.2）。"""
        with database.session_scope(self._session_factory) as session:
            account = session.get(Account, account_id)
            if account is None:
                raise NotFoundError(f"账户 #{account_id} 不存在")
            account.is_active = is_active
        logger.info("账户 #%d 状态 -> %s", account_id, is_active)

    def move_account(self, account_id: int, direction: str) -> None:
        """上移/下移账户（用户反馈：下拉框顺序自定义）。"""
        if direction not in ("up", "down"):
            raise ValidationError("移动方向无效")
        with database.session_scope(self._session_factory) as session:
            accounts = session.scalars(
                select(Account).order_by(Account.sort_order, Account.name)
            ).all()
            self._move_in_list(accounts, account_id, direction, "账户")

    def delete_account(self, account_id: int) -> None:
        """删除账户（仅限已停用）。历史交易引用置空（软外键），不受影响。"""
        with database.session_scope(self._session_factory) as session:
            account = session.get(Account, account_id)
            if account is None:
                raise NotFoundError(f"账户 #{account_id} 不存在")
            if account.is_active:
                raise ValidationError("只能删除已停用的账户，请先停用")
            session.delete(account)
        logger.info("删除账户 #%d", account_id)

    # ================= 分类 Category =================

    def list_active_categories(self, category_type: str) -> list[IdName]:
        """某类型（income / expense）下所有启用中的分类（按自定义排序；未排序时按名称）。"""
        if category_type not in _TYPE_VALUES:
            raise ValueError(f"无效的分类类型: {category_type!r}")
        with database.session_scope(self._session_factory) as session:
            categories = session.scalars(
                select(Category)
                .where(Category.type == category_type, Category.is_active.is_(True))
                .order_by(Category.sort_order, Category.name)
            )
            return [IdName(c.id, c.name) for c in categories]

    def list_all_categories(self) -> list[CategoryInfo]:
        """全部分类（含停用），带交易数（管理页用）。"""
        with database.session_scope(self._session_factory) as session:
            categories = session.scalars(
                select(Category).order_by(Category.type, Category.sort_order, Category.name)
            )
            counts = self._transaction_counts(session, Transaction.category_id)
            return [
                CategoryInfo(
                    id=c.id,
                    name=c.name,
                    type=c.type,
                    description=c.description,
                    is_active=c.is_active,
                    transaction_count=counts.get(c.id, 0),
                )
                for c in categories
            ]

    def create_category(self, name: str, type: str, description: str = "") -> int:
        """新增分类；同一类型内名称唯一。"""
        if type not in _TYPE_VALUES:
            raise ValidationError("分类类型无效")
        name = _clean_name(name, "分类")
        description = _clean_description(description)
        with database.session_scope(self._session_factory) as session:
            duplicate = session.scalar(
                select(Category).where(Category.name == name, Category.type == type)
            )
            if duplicate:
                raise ValidationError("该类型的分类名称已存在")
            max_order = session.scalar(select(func.max(Category.sort_order))) or 0
            category = Category(
                name=name,
                type=type,
                description=description,
                sort_order=max_order + 1,  # 新分类追加到列表末尾
            )
            session.add(category)
            session.flush()
            category_id = category.id
        logger.info("新增分类 #%d：%s（%s）", category_id, name, type)
        return category_id

    def update_category(self, category_id: int, name: str, description: str = "") -> None:
        """编辑分类名称/描述。

        类型不可修改：历史交易依赖分类类型，改类型会破坏统计一致性（需求 §39）。
        """
        name = _clean_name(name, "分类")
        description = _clean_description(description)
        with database.session_scope(self._session_factory) as session:
            category = session.get(Category, category_id)
            if category is None:
                raise NotFoundError(f"分类 #{category_id} 不存在")
            duplicate = session.scalar(
                select(Category).where(
                    Category.name == name,
                    Category.type == category.type,
                    Category.id != category_id,
                )
            )
            if duplicate:
                raise ValidationError("该类型的分类名称已存在")
            category.name = name
            category.description = description
        logger.info("更新分类 #%d：%s", category_id, name)

    def set_category_active(self, category_id: int, is_active: bool) -> None:
        """启用/停用分类。Other 是自动映射分类，不允许停用（需求 §4.5）。"""
        with database.session_scope(self._session_factory) as session:
            category = session.get(Category, category_id)
            if category is None:
                raise NotFoundError(f"分类 #{category_id} 不存在")
            if not is_active and category.name == "Other":
                raise ValidationError("Other 是系统自动映射分类，不能停用")
            category.is_active = is_active
        logger.info("分类 #%d 状态 -> %s", category_id, is_active)

    def move_category(self, category_id: int, direction: str) -> None:
        """上移/下移分类（仅在其类型组内移动：收入与支出分类各自排序）。"""
        if direction not in ("up", "down"):
            raise ValidationError("移动方向无效")
        with database.session_scope(self._session_factory) as session:
            category = session.get(Category, category_id)
            if category is None:
                raise NotFoundError(f"分类 #{category_id} 不存在")
            siblings = session.scalars(
                select(Category)
                .where(Category.type == category.type)
                .order_by(Category.sort_order, Category.name)
            ).all()
            self._move_in_list(siblings, category_id, direction, "分类")

    def delete_category(self, category_id: int) -> None:
        """删除分类（仅限已停用）。Other 是自动映射分类，不允许删除（需求 §4.5）。"""
        with database.session_scope(self._session_factory) as session:
            category = session.get(Category, category_id)
            if category is None:
                raise NotFoundError(f"分类 #{category_id} 不存在")
            if category.name == "Other":
                raise ValidationError("Other 是系统自动映射分类，不能删除")
            if category.is_active:
                raise ValidationError("只能删除已停用的分类，请先停用")
            session.delete(category)
        logger.info("删除分类 #%d", category_id)

    def get_other_category(self, category_type: str) -> IdName | None:
        """对应类型的 Other 分类（需求 §4.5 自动映射用）。"""
        if category_type not in _TYPE_VALUES:
            raise ValueError(f"无效的分类类型: {category_type!r}")
        with database.session_scope(self._session_factory) as session:
            category = session.scalar(
                select(Category).where(
                    Category.name == "Other",
                    Category.type == category_type,
                    Category.is_active.is_(True),
                )
            )
            return IdName(category.id, category.name) if category else None

    # ================= 内部 =================

    @staticmethod
    def _transaction_counts(session, column) -> dict[int, int]:
        """一次 GROUP BY 查询各实体的交易数（避免 N+1）。"""
        rows = session.execute(
            select(column, func.count()).select_from(Transaction).group_by(column)
        )
        return {entity_id: count for entity_id, count in rows}
