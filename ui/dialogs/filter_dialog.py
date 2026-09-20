"""历史记录筛选弹窗：类型 / 渠道 / 账户 / 分类 / 日期范围。"""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from services.catalog_service import CatalogService


class FilterDialog(QDialog):
    """筛选条件编辑。应用/清除后关闭，调用方读取 filters()。"""

    def __init__(self, catalog_service: CatalogService, current: dict | None = None, parent=None) -> None:
        super().__init__(parent)
        self._catalog = catalog_service
        current = current or {}
        self.setWindowTitle("筛选")
        self.setMinimumWidth(380)

        self.type_combo = QComboBox()
        self.type_combo.addItem("全部", None)
        self.type_combo.addItem("收入", "income")
        self.type_combo.addItem("支出", "expense")

        self.channel_combo = QComboBox()
        self.channel_combo.addItem("全部", None)
        for channel in catalog_service.list_all_channels():
            self.channel_combo.addItem(channel.name, channel.id)

        self.account_combo = QComboBox()
        self.account_combo.addItem("全部", None)
        for account in catalog_service.list_all_accounts():
            self.account_combo.addItem(account.name, account.id)

        self.category_combo = QComboBox()
        self.category_combo.addItem("全部", None)
        for category in catalog_service.list_all_categories():
            label = f"{'收入' if category.type == 'income' else '支出'} · {category.name}"
            self.category_combo.addItem(label, category.id)

        self.date_from_check = QCheckBox("从")
        self.date_from_edit = self._date_edit()
        self.date_to_check = QCheckBox("至")
        self.date_to_edit = self._date_edit()
        self.date_from_check.toggled.connect(self.date_from_edit.setEnabled)
        self.date_to_check.toggled.connect(self.date_to_edit.setEnabled)

        from_row = QHBoxLayout()
        from_row.addWidget(self.date_from_check)
        from_row.addWidget(self.date_from_edit, 1)
        to_row = QHBoxLayout()
        to_row.addWidget(self.date_to_check)
        to_row.addWidget(self.date_to_edit, 1)

        form = QFormLayout()
        form.addRow("类型", self.type_combo)
        form.addRow("渠道", self.channel_combo)
        form.addRow("账户", self.account_combo)
        form.addRow("分类", self.category_combo)
        form.addRow("起始日期", from_row)
        form.addRow("结束日期", to_row)

        hint = QLabel("所有条件同时生效（AND）；日期为闭区间。")
        hint.setObjectName("dialogInfo")

        self.apply_button = QPushButton("应用")
        self.clear_button = QPushButton("清除")
        self.cancel_button = QPushButton("取消")
        self.apply_button.clicked.connect(self.accept)
        self.clear_button.clicked.connect(self._on_clear)
        self.cancel_button.clicked.connect(self.reject)
        button_row = QHBoxLayout()
        button_row.addStretch(1)
        button_row.addWidget(self.clear_button)
        button_row.addWidget(self.cancel_button)
        button_row.addWidget(self.apply_button)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(hint)
        layout.addLayout(button_row)

        # 回填当前筛选
        self._set_combo(self.type_combo, current.get("type"))
        self._set_combo(self.channel_combo, current.get("channel_id"))
        self._set_combo(self.account_combo, current.get("account_id"))
        self._set_combo(self.category_combo, current.get("category_id"))
        if current.get("date_from"):
            self.date_from_check.setChecked(True)
            self.date_from_edit.setDate(self._to_qdate(current["date_from"]))
        if current.get("date_to"):
            self.date_to_check.setChecked(True)
            self.date_to_edit.setDate(self._to_qdate(current["date_to"]))

    def filters(self) -> dict:
        """当前筛选条件（仅包含已启用的项）。"""
        result: dict = {}
        if self.type_combo.currentData():
            result["type"] = self.type_combo.currentData()
        if self.channel_combo.currentData():
            result["channel_id"] = self.channel_combo.currentData()
        if self.account_combo.currentData():
            result["account_id"] = self.account_combo.currentData()
        if self.category_combo.currentData():
            result["category_id"] = self.category_combo.currentData()
        if self.date_from_check.isChecked():
            result["date_from"] = self._edit_date(self.date_from_edit)
        if self.date_to_check.isChecked():
            result["date_to"] = self._edit_date(self.date_to_edit)
        return result

    def _on_clear(self) -> None:
        for combo in (self.type_combo, self.channel_combo, self.account_combo, self.category_combo):
            combo.setCurrentIndex(0)
        self.date_from_check.setChecked(False)
        self.date_to_check.setChecked(False)
        self.accept()

    @staticmethod
    def _date_edit() -> QDateEdit:
        edit = QDateEdit()
        edit.setCalendarPopup(True)
        edit.setDisplayFormat("yyyy-MM-dd")
        edit.setDate(QDate.currentDate())
        edit.setMinimumDate(QDate(1900, 1, 1))
        edit.setMaximumDate(QDate(3000, 12, 31))
        edit.setEnabled(False)
        return edit

    @staticmethod
    def _set_combo(combo: QComboBox, value) -> None:
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    @staticmethod
    def _to_qdate(value: date) -> QDate:
        return QDate(value.year, value.month, value.day)

    @staticmethod
    def _edit_date(edit: QDateEdit) -> date:
        qdate = edit.date()
        return date(qdate.year(), qdate.month(), qdate.day())
