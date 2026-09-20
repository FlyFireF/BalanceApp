"""编辑交易弹窗（需求 §12：编辑可使用弹窗）。"""

from __future__ import annotations

import logging

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QMessageBox,
    QVBoxLayout,
)

from services.dto import TransactionRecord
from services.exceptions import ValidationError
from services.transaction_service import TransactionService
from ui.widgets.transaction_form import TransactionForm

logger = logging.getLogger(__name__)


class TransactionDialog(QDialog):
    """编辑交易：表单预填，保存后提交 update，成功则关闭。"""

    def __init__(
        self,
        catalog_service,
        transaction_service: TransactionService,
        record: TransactionRecord,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._transaction_service = transaction_service
        self._record = record
        kind = "收入" if record.type == "income" else "支出"
        self.setWindowTitle(f"编辑{kind}")

        title = QLabel(f"编辑{kind}")
        title.setObjectName("cardTitle")

        self._form = TransactionForm(catalog_service)
        self._form.set_record(record)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        save_button = buttons.button(QDialogButtonBox.Save)
        save_button.setText("保存")
        save_button.setObjectName("primaryButton")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(self._form)
        layout.addWidget(buttons)
        self.setMinimumWidth(400)

    def _on_save(self) -> None:
        if not self._form.has_options():
            QMessageBox.warning(self, "无法保存", "渠道、账户或分类列表为空。")
            return
        try:
            data = self._form.data()
        except ValueError as exc:
            QMessageBox.warning(self, "无法保存", str(exc))
            return
        try:
            self._transaction_service.update(self._record.id, **data)
        except ValidationError as exc:
            QMessageBox.warning(self, "无法保存", str(exc))
            return
        except Exception:
            logger.exception("编辑交易失败")
            QMessageBox.critical(self, "错误", "保存失败，请查看日志。")
            return
        self.accept()
