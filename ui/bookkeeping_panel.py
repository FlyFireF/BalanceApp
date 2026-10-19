"""直接记账面板：打开应用即可记账，无需额外窗口（需求 §11）。"""

from __future__ import annotations

import logging

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from services.exceptions import ValidationError
from services.transaction_service import TransactionService
from ui.widgets.transaction_form import TransactionForm
from utils.currency import format_money

logger = logging.getLogger(__name__)


class BookkeepingPanel(QFrame):
    """记账表单卡片。保存成功后发出 transaction_saved 信号。"""

    transaction_saved = Signal()

    def __init__(
        self,
        catalog_service,
        transaction_service: TransactionService,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self._transaction_service = transaction_service

        title = QLabel("记账")
        title.setObjectName("cardTitle")

        self._form = TransactionForm(catalog_service)
        self._form.setMaximumWidth(560)

        self.save_button = QPushButton("保存")
        self.save_button.setObjectName("primaryButton")
        self.save_button.clicked.connect(self.save_transaction)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusLabel")

        bottom_row = QHBoxLayout()
        bottom_row.addWidget(self.save_button)
        bottom_row.addWidget(self.status_label)
        bottom_row.addStretch(1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.addWidget(title)
        layout.addWidget(self._form)
        layout.addLayout(bottom_row)

        # 回车 = 保存（用户需求）：焦点在记账页任意元素时均生效，
        # 包括金额/备注/标签输入框、日期、下拉框、收入/支出单选与保存按钮。
        for widget in (self, *self.findChildren(QWidget)):
            widget.installEventFilter(self)

    @property
    def form(self) -> TransactionForm:
        """暴露表单（测试与外部联动使用）。"""
        return self._form

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """拦截记账页内的 Enter / 小键盘 Enter，触发保存。

        下拉框选项列表、日期日历等弹出的子窗口不拦截，回车仍交给弹窗
        用于选中条目（这些控件位于独立的 popup 窗口中，window() 不同）。
        """
        if (
            event.type() == QEvent.KeyPress
            and event.key() in (Qt.Key_Return, Qt.Key_Enter)
            and isinstance(watched, QWidget)
            and watched.window() is self.window()
            and QApplication.activePopupWidget() is None
        ):
            self.save_transaction()
            return True
        return super().eventFilter(watched, event)

    def save_transaction(self) -> None:
        """校验并保存当前表单；成功则清空输入、保留默认值并发出信号。"""
        if not self._form.has_options():
            QMessageBox.warning(self, "无法保存", "渠道、账户或分类列表为空，请先在管理页面添加。")
            return
        try:
            data = self._form.data()
        except ValueError as exc:  # 客户端校验失败（金额无效等）
            QMessageBox.warning(self, "无法保存", str(exc))
            return
        try:
            self._transaction_service.create(**data)
        except ValidationError as exc:
            QMessageBox.warning(self, "无法保存", str(exc))
            return
        except Exception:
            logger.exception("保存交易失败")
            QMessageBox.critical(self, "错误", "保存失败，请查看日志。")
            return

        self._form.reset_after_save()
        kind = "收入" if data["type"] == "income" else "支出"
        self.status_label.setText(f"✓ 已保存 {kind} {format_money(data['amount'])}")
        self.transaction_saved.emit()
