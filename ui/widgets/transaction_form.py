"""记账表单：收入/支出切换 + 金额/日期/渠道/账户/分类/备注/标签。

BookkeepingPanel（直接记账）与 TransactionDialog（编辑弹窗）共用此表单，
避免重复代码（需求 §56）。
"""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import QDate, QRegularExpression, Qt
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDateEdit,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QRadioButton,
    QWidget,
)

from services.catalog_service import CatalogService
from services.dto import IdName, TransactionRecord
from utils.currency import parse_amount


class TransactionForm(QWidget):
    """收入/支出表单。数据校验由 data() + 服务层共同完成。"""

    def __init__(self, catalog_service: CatalogService, parent=None) -> None:
        super().__init__(parent)
        self._catalog = catalog_service

        # 收入 / 支出 切换（默认支出，记账最高频）
        self.income_radio = QRadioButton("收入")
        self.expense_radio = QRadioButton("支出")
        self.expense_radio.setChecked(True)
        self._type_group = QButtonGroup(self)
        self._type_group.addButton(self.income_radio)
        self._type_group.addButton(self.expense_radio)
        self._type_group.buttonToggled.connect(self._on_type_toggled)

        # 金额：仅允许数字 + 最多两位小数（正则输入校验）
        self.amount_edit = QLineEdit()
        self.amount_edit.setPlaceholderText("0.00")
        self.amount_edit.setValidator(
            QRegularExpressionValidator(QRegularExpression(r"^\d*(\.\d{0,2})?$"), self)
        )

        # 日期：默认今天，可弹日历选择（需求 §4.5）；范围 1900~3000
        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        self.date_edit.setDate(QDate.currentDate())
        self.date_edit.setMinimumDate(QDate(1900, 1, 1))
        self.date_edit.setMaximumDate(QDate(3000, 12, 31))

        self.channel_combo = QComboBox()
        self.account_combo = QComboBox()
        self.category_combo = QComboBox()

        self.note_edit = QLineEdit()
        self.note_edit.setPlaceholderText("备注（可选）")
        self.tags_edit = QLineEdit()
        self.tags_edit.setPlaceholderText("标签，逗号分隔（可选）")

        type_row = QWidget()
        type_layout = QHBoxLayout(type_row)
        type_layout.setContentsMargins(0, 0, 0, 0)
        type_layout.addWidget(self.income_radio)
        type_layout.addWidget(self.expense_radio)
        type_layout.addStretch(1)

        layout = QFormLayout(self)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.setSpacing(8)
        layout.setLabelAlignment(Qt.AlignRight)
        layout.addRow("类型", type_row)
        layout.addRow("金额", self.amount_edit)
        layout.addRow("日期", self.date_edit)
        layout.addRow("渠道", self.channel_combo)
        layout.addRow("账户", self.account_combo)
        layout.addRow("分类", self.category_combo)
        layout.addRow("备注", self.note_edit)
        layout.addRow("标签", self.tags_edit)

        self.reload_options()

    # ---------- 对外方法 ----------

    def reload_options(self) -> None:
        """重新加载渠道/账户/分类选项（实体变化后由外部调用）。"""
        self._reload_combo(self.channel_combo, self._catalog.list_active_channels())
        self._reload_combo(self.account_combo, self._catalog.list_active_accounts())
        self._reload_categories()

    def set_type(self, transaction_type: str) -> None:
        """切换收入/支出（并联动刷新分类）。"""
        if transaction_type == "income":
            self.income_radio.setChecked(True)
        else:
            self.expense_radio.setChecked(True)
        self._reload_categories()

    def type(self) -> str:
        """当前类型：income / expense。"""
        return "income" if self.income_radio.isChecked() else "expense"

    def set_record(self, record: TransactionRecord) -> None:
        """用已有交易填充表单（编辑模式）。

        若引用的渠道/账户/分类已停用（不在下拉中），会临时追加「（已停用）」项
        并保持选中，避免编辑旧交易时值被静默改写。
        """
        self.set_type(record.type)
        self.amount_edit.setText(f"{record.amount:.2f}")
        self.date_edit.setDate(QDate(record.date.year, record.date.month, record.date.day))
        self._select_or_append(self.channel_combo, record.channel_id, record.channel_name)
        self._select_or_append(self.account_combo, record.account_id, record.account_name)
        self._select_or_append(self.category_combo, record.category_id, record.category_name)
        self.note_edit.setText(record.note)
        self.tags_edit.setText(record.tags)

    def reset_after_save(self) -> None:
        """保存成功后：清空输入，保留合理默认值（需求 §11）。"""
        self.amount_edit.clear()
        self.note_edit.clear()
        self.tags_edit.clear()
        # 保留：类型、日期、渠道/账户/分类选择（连续记账更方便）

    def data(self) -> dict:
        """收集表单数据。

        Raises:
            ValueError: 金额无效（中文提示）。
        """
        qdate = self.date_edit.date()
        return {
            "type": self.type(),
            "amount": parse_amount(self.amount_edit.text()),
            "date": date(qdate.year(), qdate.month(), qdate.day()),
            "channel_id": self.channel_combo.currentData(),
            "account_id": self.account_combo.currentData(),
            "category_id": self.category_combo.currentData(),
            "note": self.note_edit.text(),
            "tags": self.tags_edit.text(),
        }

    def has_options(self) -> bool:
        """渠道/账户/分类是否都有可选项。"""
        return all(
            combo.count() > 0
            for combo in (self.channel_combo, self.account_combo, self.category_combo)
        )

    # ---------- 内部 ----------

    def _on_type_toggled(self) -> None:
        self._reload_categories()

    def _reload_categories(self) -> None:
        """按当前类型加载分类，默认选中 Other。"""
        options = self._catalog.list_active_categories(self.type())
        self._reload_combo(self.category_combo, options)
        self._select_by_name(self.category_combo, "Other")

    def _reload_combo(self, combo: QComboBox, options: list[IdName]) -> None:
        combo.blockSignals(True)
        combo.clear()
        for option in options:
            combo.addItem(option.name, option.id)
        combo.blockSignals(False)

    def _select_or_append(self, combo: QComboBox, item_id: int | None, name: str | None) -> None:
        """选中指定 id；不存在则临时追加（编辑引用已停用/已删除实体的旧交易时）。"""
        if item_id is None:
            # 实体已被删除（软外键置空）：追加占位项并保持为空引用
            combo.addItem("（已删除）", None)
            combo.setCurrentIndex(combo.count() - 1)
            return
        index = combo.findData(item_id)
        if index < 0:
            combo.addItem(f"{name}（已停用）", item_id)
            index = combo.count() - 1
        combo.setCurrentIndex(index)

    def _select_by_name(self, combo: QComboBox, name: str) -> None:
        index = combo.findText(name)
        if index >= 0:
            combo.setCurrentIndex(index)
