"""月度统计服务（需求 §16/§17/§18/§23/§25 + 用户确认的月度百分比口径）。

数据范围（务必区分，需求 §25）：
- 本月收入/支出/净额：仅统计选定月份内（月初 ~ 月末）的交易；
- 渠道累计收入/支出：截至选定月份最后一天的全部历史交易；
- 渠道余额 = 渠道累计收入 - 渠道累计支出（需求 §18，不是本月净额！）；
- 渠道余额百分比（用户确认的月度口径）：
    (本月固定收入 + 本月该渠道其他收入 - 本月该渠道支出)
  / (本月固定收入 + 本月该渠道其他收入)
  即「本月净额 / 本月收入」，每月重新计算（原文档 §19 的累计口径已被
  用户以月度口径取代，详见对话确认）；
- 账户余额 = 初始余额 + 截至选定月末的累计收入 - 累计支出（需求 §25）。

百分比边界（沿用需求 §20）：
- 本月收入 = 0 → 返回 None（UI 显示 N/A，进度条 0%）；
- 本月净额 < 0 → 0%（UI 用红色）；
- 净额 > 收入 → 封顶 100%。

所有金额运算使用 Decimal，绝不使用 float（需求 §40）。
"""

from __future__ import annotations

import calendar
import logging
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from database import database
from database.models import Account, CategoryType, Channel, Transaction
from database.repositories.transaction_repository import TransactionRepository
from services.dto import AccountBalance, ChannelStatistics, MonthStatistics
from services.exceptions import ValidationError

logger = logging.getLogger(__name__)

_ZERO = Decimal("0")
_PERCENT_MAX = Decimal("100")
_PERCENT_QUANT = Decimal("0.01")


def balance_percent(income: Decimal, balance: Decimal) -> Decimal | None:
    """余额百分比 = 余额 / 收入 × 100%（纯函数，便于单测边界）。

    当前用于「月度口径」：income = 本月收入，balance = 本月净额。

    - 收入为 0 → None（N/A）；
    - 结果封顶在 [0, 100]，四舍五入保留两位小数。
    """
    if income <= 0:
        return None
    ratio = (balance / income) * 100
    capped = max(_ZERO, min(_PERCENT_MAX, ratio))
    return capped.quantize(_PERCENT_QUANT, rounding=ROUND_HALF_UP)


def _months_between(start: date, end: date) -> int:
    """从 start 所在月份到 end 所在月份（含两端）的月数；start 晚于 end 时为 0。"""
    total = (end.year - start.year) * 12 + (end.month - start.month) + 1
    return max(0, total)


class StatisticsService:
    """月度统计服务：Dashboard 的数据来源。"""

    def __init__(self, session_factory: sessionmaker | None = None) -> None:
        self._session_factory = session_factory or database.get_session_factory()

    def month_statistics(self, year: int, month: int) -> MonthStatistics:
        """计算指定年月的完整统计。

        Raises:
            ValidationError: 月份不合法。
        """
        if not 1 <= month <= 12:
            raise ValidationError(f"月份无效：{month}")
        month_start = date(year, month, 1)
        month_end = date(year, month, calendar.monthrange(year, month)[1])

        with database.session_scope(self._session_factory) as session:
            transactions = TransactionRepository(session).list_up_to(month_end)

            month_income = _ZERO
            month_expense = _ZERO
            channel_data: dict[int, dict[str, Decimal]] = {}
            account_net: dict[int, Decimal] = {}

            for tx in transactions:
                is_income = tx.type == CategoryType.INCOME.value
                signed = tx.amount if is_income else -tx.amount
                account_net[tx.account_id] = account_net.get(tx.account_id, _ZERO) + signed

                data = channel_data.setdefault(
                    tx.channel_id,
                    {
                        "cum_income": _ZERO,
                        "cum_expense": _ZERO,
                        "month_income": _ZERO,
                        "month_expense": _ZERO,
                    },
                )
                if is_income:
                    data["cum_income"] += tx.amount
                else:
                    data["cum_expense"] += tx.amount

                if month_start <= tx.date <= month_end:
                    if is_income:
                        month_income += tx.amount
                        data["month_income"] += tx.amount
                    else:
                        month_expense += tx.amount
                        data["month_expense"] += tx.amount

            # 每月固定金额（用户确认的功能）：启用中的渠道，其每月固定金额
            # 计入本月收入与累计收入（从渠道创建月份起算，不产生真实交易）。
            active_channels = session.scalars(
                select(Channel).where(Channel.is_active.is_(True))
            ).all()
            for channel in active_channels:
                if channel.monthly_amount <= 0:
                    continue
                fixed = channel.monthly_amount
                months = _months_between(channel.created_at.date(), month_end)
                if months <= 0:
                    continue  # 查看渠道创建前的月份：固定金额不计入
                month_income += fixed
                data = channel_data.setdefault(
                    channel.id,
                    {
                        "cum_income": _ZERO,
                        "cum_expense": _ZERO,
                        "month_income": _ZERO,
                        "month_expense": _ZERO,
                    },
                )
                data["month_income"] += fixed
                data["cum_income"] += fixed * months

            channels = self._build_channel_rows(session, channel_data)
            accounts = self._build_account_rows(session, account_net)

        return MonthStatistics(
            year=year,
            month=month,
            month_income=month_income,
            month_expense=month_expense,
            month_net=month_income - month_expense,
            channels=channels,
            accounts=accounts,
        )

    @staticmethod
    def _build_channel_rows(
        session, channel_data: dict[int, dict[str, Decimal]]
    ) -> list[ChannelStatistics]:
        """渠道统计行。

        展示规则：启用中的渠道全部展示（无交易显示 0 / N/A）；
        停用渠道仅在有历史交易时展示（余额仍需可见，需求 §4.1/§39）。
        """
        rows: list[ChannelStatistics] = []
        channels = session.scalars(
            select(Channel).order_by(Channel.sort_order, Channel.name)
        )
        for channel in channels:
            data = channel_data.get(channel.id)
            if data is None and not channel.is_active:
                continue
            cumulative_income = data["cum_income"] if data else _ZERO
            cumulative_expense = data["cum_expense"] if data else _ZERO
            balance = cumulative_income - cumulative_expense
            month_income = data["month_income"] if data else _ZERO
            month_expense = data["month_expense"] if data else _ZERO
            rows.append(
                ChannelStatistics(
                    channel_id=channel.id,
                    channel_name=channel.name,
                    is_active=channel.is_active,
                    monthly_amount=channel.monthly_amount,
                    month_income=month_income,
                    month_expense=month_expense,
                    cumulative_income=cumulative_income,
                    cumulative_expense=cumulative_expense,
                    balance=balance,
                    # 月度口径百分比（用户确认）：本月净额 / 本月收入，每月重新计算
                    balance_percent=balance_percent(month_income, month_income - month_expense),
                )
            )
        return rows

    @staticmethod
    def _build_account_rows(
        session, account_net: dict[int, Decimal]
    ) -> list[AccountBalance]:
        """账户余额行：初始余额 + 截至选定月末的累计净流入（需求 §25）。

        展示规则同渠道：启用中的全部展示；停用仅在有历史交易时展示。
        """
        rows: list[AccountBalance] = []
        accounts = session.scalars(
            select(Account).order_by(Account.sort_order, Account.name)
        )
        for account in accounts:
            net = account_net.get(account.id)
            if net is None and not account.is_active:
                continue
            rows.append(
                AccountBalance(
                    account_id=account.id,
                    account_name=account.name,
                    is_active=account.is_active,
                    initial_balance=account.initial_balance,
                    balance=account.initial_balance + (net if net is not None else _ZERO),
                )
            )
        return rows
