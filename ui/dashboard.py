"""右侧月度 Dashboard（需求 §15-§24/§42）。

结构：
- 月份切换：‹ 2026年9月 › + 「选择」弹日历直接选任意月份（需求 §15 B+C 方案）；
- 本月统计卡片：本月收入 / 本月支出 / 本月净额（需求 §16）；
- 渠道 / 账户总览：每个渠道一张卡片——累计收入、累计支出、余额、余额百分比
  与渐变进度条（需求 §17-§21，这是本项目的核心展示区）；
- 实际账户：名称 + 余额列表，视觉优先级低于渠道（需求 §22）；
- 空数据友好提示（需求 §42）。

进度条颜色（需求 §21）：在 HSV 色相上按百分比连续插值——
0% 红 → 60° 黄 → 120° 绿，百分比越高越绿、越低越红；
N/A 为中性灰；余额为负固定红色（进度 0%）。
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCalendarWidget,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from services.dto import AccountBalance, ChannelStatistics
from services.statistics_service import StatisticsService
from ui import theme
from utils.currency import format_money

logger = logging.getLogger(__name__)


def _format_percent(percent: Decimal | None) -> str:
    """百分比文本：None → N/A；去除多余小数零（81.25% / 80% / 0%）。"""
    if percent is None:
        return "N/A"
    text = f"{percent:f}".rstrip("0").rstrip(".")
    if not text:
        text = "0"
    return f"{text}%"


def _percent_color(percent: Decimal | None) -> QColor:
    """百分比 → 颜色：HSV 色相连续插值，红(0%) → 黄(50%) → 绿(100%)（需求 §21）。"""
    if percent is None:
        return QColor("#d1d5db")  # N/A 中性灰
    hue = float(percent) / 100.0 * (120.0 / 360.0)
    return QColor.fromHsvF(hue, 0.75, 0.85)


class ChannelCard(QFrame):
    """单个渠道的统计卡片（需求 §17）。"""

    def __init__(self, stat: ChannelStatistics, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("channelCard")
        self.stat = stat

        self.name_label = QLabel(stat.channel_name)
        self.name_label.setObjectName("channelName")

        self.percent_label = QLabel(_format_percent(stat.balance_percent))
        self.percent_label.setObjectName("percentLabel")

        name_row = QHBoxLayout()
        name_row.setContentsMargins(0, 0, 0, 0)
        name_row.addWidget(self.name_label)
        if not stat.is_active:
            tag = QLabel("已停用")
            tag.setObjectName("inactiveTag")
            name_row.addWidget(tag)
        name_row.addStretch(1)
        name_row.addWidget(self.percent_label)

        month_parts = [
            f"本月 收入 {format_money(stat.month_income)}",
            f"支出 {format_money(stat.month_expense)}",
        ]
        if stat.monthly_amount > 0:
            month_parts.append(f"固定 {format_money(stat.monthly_amount)}")
        self.month_metric_label = QLabel("　".join(month_parts))
        self.month_metric_label.setObjectName("metricLabel")

        self.cum_metric_label = QLabel(
            f"累计 收入 {format_money(stat.cumulative_income)}　"
            f"支出 {format_money(stat.cumulative_expense)}"
        )
        self.cum_metric_label.setObjectName("metricLabel")

        self.balance_label = QLabel(f"余额 {format_money(stat.balance)}")
        self.balance_label.setObjectName("balanceLabel")

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setTextVisible(False)
        percent = stat.balance_percent
        self.progress.setValue(int(percent) if percent is not None else 0)

        color = _percent_color(percent)
        if stat.balance < 0:
            # 需求 §20：负余额固定红色（颜色随主题）
            color = QColor(theme.color("red"))
            self.balance_label.setStyleSheet(f"color: {theme.color('red')};")
            self.percent_label.setStyleSheet(f"color: {theme.color('red')};")
        elif percent is not None:
            self.percent_label.setStyleSheet(f"color: {color.name()};")
        self.progress.setStyleSheet(
            f"QProgressBar::chunk {{ background: {color.name()}; border-radius: 4px; }}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(3)
        layout.addLayout(name_row)
        layout.addWidget(self.month_metric_label)
        layout.addWidget(self.cum_metric_label)
        layout.addWidget(self.balance_label)
        layout.addWidget(self.progress)


class DashboardPanel(QFrame):
    """右侧月度 Dashboard 面板。数据来源：StatisticsService。"""

    def __init__(self, statistics_service: StatisticsService, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self._statistics_service = statistics_service
        today = date.today()
        self._year, self._month = today.year, today.month

        # ---------- 月份切换（需求 §15）----------
        self.prev_button = QPushButton("‹")
        self.prev_button.setObjectName("monthButton")
        self.next_button = QPushButton("›")
        self.next_button.setObjectName("monthButton")
        self.picker_button = QPushButton("选择")
        self.month_label = QLabel()
        self.month_label.setObjectName("monthLabel")
        self.prev_button.clicked.connect(self.prev_month)
        self.next_button.clicked.connect(self.next_month)
        self.picker_button.clicked.connect(self._open_month_picker)

        header = QHBoxLayout()
        header.addWidget(self.prev_button)
        header.addStretch(1)
        header.addWidget(self.month_label)
        header.addStretch(1)
        header.addWidget(self.next_button)
        header.addSpacing(6)
        header.addWidget(self.picker_button)

        # ---------- 本月统计（需求 §16）----------
        self.income_value_label, income_card = self._stat_card("本月收入")
        self.expense_value_label, expense_card = self._stat_card("本月支出")
        self.net_value_label, net_card = self._stat_card("本月净额")

        cards_row = QHBoxLayout()
        cards_row.setSpacing(8)
        cards_row.addWidget(income_card)
        cards_row.addWidget(expense_card)
        cards_row.addWidget(net_card)

        # ---------- 滚动内容：渠道总览 + 实际账户 ----------
        self.empty_label = QLabel()
        self.empty_label.setObjectName("emptyLabel")
        self.empty_label.setWordWrap(True)
        self.empty_label.setAlignment(Qt.AlignCenter)

        self.channel_layout = QVBoxLayout()
        self.channel_layout.setSpacing(8)
        self.accounts_layout = QVBoxLayout()
        self.accounts_layout.setSpacing(2)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 4, 0, 0)
        content_layout.setSpacing(6)
        content_layout.addWidget(self.empty_label)
        content_layout.addWidget(self._section_title("渠道 / 账户总览"))
        content_layout.addLayout(self.channel_layout)
        content_layout.addSpacing(8)
        content_layout.addWidget(self._section_title("实际账户"))
        content_layout.addLayout(self.accounts_layout)
        content_layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)  # 原生滚动区自带边框，卡片内需去掉
        scroll.setWidget(content)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        main = QVBoxLayout(self)
        main.setContentsMargins(12, 12, 12, 12)
        main.setSpacing(8)
        main.addLayout(header)
        main.addLayout(cards_row)
        main.addWidget(scroll, 1)

        self.channel_cards: list[ChannelCard] = []
        self.account_rows: list[QWidget] = []

        self.set_month(self._year, self._month)

    # ---------- 月份切换 ----------

    def prev_month(self) -> None:
        year, month = self._year, self._month - 1
        if month == 0:
            year, month = year - 1, 12
        self.set_month(year, month)

    def next_month(self) -> None:
        year, month = self._year, self._month + 1
        if month == 13:
            year, month = year + 1, 1
        self.set_month(year, month)

    def set_month(self, year: int, month: int) -> None:
        """切换到指定年月并刷新。"""
        self._year, self._month = year, month
        self.month_label.setText(f"{year}年{month}月")
        self.refresh()

    def _open_month_picker(self) -> None:
        """日历弹窗：直接选择任意月份（需求 §15 方案 C）。"""
        dialog = QDialog(self)
        dialog.setWindowTitle("选择月份")
        calendar = QCalendarWidget(dialog)
        calendar.setSelectedDate(self._month_qdate())
        calendar.clicked.connect(lambda qdate: self._on_calendar_clicked(qdate, dialog))
        layout = QVBoxLayout(dialog)
        layout.addWidget(calendar)
        dialog.exec()

    def _on_calendar_clicked(self, qdate, dialog: QDialog) -> None:
        self.set_month(qdate.year(), qdate.month())
        dialog.accept()

    def _month_qdate(self) -> QDate:
        return QDate(self._year, self._month, 1)

    # ---------- 刷新 ----------

    def refresh(self) -> None:
        """重新计算并渲染全部统计。数据变化后由主窗口调用（需求 §39）。"""
        try:
            stats = self._statistics_service.month_statistics(self._year, self._month)
        except Exception:
            logger.exception("统计加载失败")
            self.empty_label.setText("统计数据加载失败，请查看日志")
            self.empty_label.show()
            return

        self.income_value_label.setText(format_money(stats.month_income))
        self.expense_value_label.setText(format_money(stats.month_expense))
        self.net_value_label.setText(format_money(stats.month_net))
        net = stats.month_net
        if net > 0:
            self.net_value_label.setStyleSheet(f"color: {theme.color('green')};")
        elif net < 0:
            self.net_value_label.setStyleSheet(f"color: {theme.color('red')};")
        else:
            self.net_value_label.setStyleSheet(f"color: {theme.color('text_primary')};")

        # 渠道卡片
        for card in self.channel_cards:
            self.channel_layout.removeWidget(card)
            card.deleteLater()
        self.channel_cards.clear()
        for stat in stats.channels:
            card = ChannelCard(stat)
            self.channel_layout.addWidget(card)
            self.channel_cards.append(card)

        # 账户行
        for row in self.account_rows:
            self.accounts_layout.removeWidget(row)
            row.deleteLater()
        self.account_rows.clear()
        for account in stats.accounts:
            row = self._build_account_row(account)
            self.accounts_layout.addWidget(row)
            self.account_rows.append(row)

        # 空数据状态（需求 §42）
        has_any_transaction = any(
            c.cumulative_income > 0 or c.cumulative_expense > 0 for c in stats.channels
        )
        month_empty = stats.month_income == 0 and stats.month_expense == 0
        if not has_any_transaction:
            self.empty_label.setText("本月暂无交易\n开始记录你的第一笔账务")
            self.empty_label.show()
        elif month_empty:
            self.empty_label.setText("本月暂无交易")
            self.empty_label.show()
        else:
            self.empty_label.hide()

    # ---------- 内部 ----------

    @staticmethod
    def _stat_card(title: str) -> tuple[QLabel, QFrame]:
        card = QFrame()
        card.setObjectName("statCard")
        title_label = QLabel(title)
        title_label.setObjectName("statTitle")
        value_label = QLabel("—")
        value_label.setObjectName("statValue")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(2)
        layout.addWidget(title_label)
        layout.addWidget(value_label)
        return value_label, card

    @staticmethod
    def _section_title(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("sectionTitle")
        return label

    @staticmethod
    def _build_account_row(account: AccountBalance) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(4, 2, 4, 2)
        name = QLabel(account.account_name)
        if not account.is_active:
            name.setStyleSheet("color: #9ca3af;")
            name.setText(f"{account.account_name}（已停用）")
        value = QLabel(format_money(account.balance))
        if account.balance < 0:
            value.setStyleSheet(f"color: {theme.color('red')}; font-weight: 600;")
        layout.addWidget(name)
        layout.addStretch(1)
        layout.addWidget(value)
        return row
