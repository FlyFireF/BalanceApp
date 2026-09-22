"""账户管理弹窗：新增 / 编辑（含初始余额）/ 停用（启用）。"""

from __future__ import annotations

import logging

from PySide6.QtCore import QRegularExpression, Qt
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from services.catalog_service import CatalogService
from services.dto import AccountInfo
from services.exceptions import NotFoundError, ValidationError
from ui.widgets.entity_table import EntityTable
from utils.currency import format_money, parse_amount

logger = logging.getLogger(__name__)


class AccountEditorDialog(QDialog):
    """新增/编辑账户：初始余额可随时编辑（需求 §27）。"""

    def __init__(
        self,
        catalog_service: CatalogService,
        parent=None,
        account: AccountInfo | None = None,
    ) -> None:
        super().__init__(parent)
        self._catalog = catalog_service
        self._account = account
        self.setWindowTitle("新增账户" if account is None else f"编辑账户：{account.name}")

        self.name_edit = QLineEdit()
        self.name_edit.setMaxLength(50)
        self.name_edit.setPlaceholderText("账户名称，如 Bank")
        self.desc_edit = QLineEdit()
        self.desc_edit.setMaxLength(200)
        self.desc_edit.setPlaceholderText("描述（可选）")

        # 初始余额：允许负数（如信用卡欠款），最多两位小数
        self.balance_edit = QLineEdit()
        self.balance_edit.setValidator(
            QRegularExpressionValidator(QRegularExpression(r"^-?\d*(\.\d{0,2})?$"), self)
        )

        if account is not None:
            self.name_edit.setText(account.name)
            self.desc_edit.setText(account.description)
            self.balance_edit.setText(f"{account.initial_balance:.2f}")
        else:
            self.balance_edit.setText("0.00")

        form = QFormLayout()
        form.addRow("名称", self.name_edit)
        form.addRow("描述", self.desc_edit)
        form.addRow("初始余额", self.balance_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        save_button = buttons.button(QDialogButtonBox.Save)
        save_button.setText("保存")
        save_button.setObjectName("primaryButton")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)
        self.setMinimumWidth(340)

    def _on_save(self) -> None:
        try:
            balance = parse_amount(self.balance_edit.text())
        except ValueError as exc:
            QMessageBox.warning(self, "无法保存", str(exc))
            return
        try:
            if self._account is None:
                self._catalog.create_account(
                    self.name_edit.text(), self.desc_edit.text(), balance
                )
            else:
                self._catalog.update_account(
                    self._account.id, self.name_edit.text(), self.desc_edit.text(), balance
                )
        except ValidationError as exc:
            QMessageBox.warning(self, "无法保存", str(exc))
            return
        except Exception:
            logger.exception("保存账户失败")
            QMessageBox.critical(self, "错误", "保存失败，请查看日志。")
            return
        self.accept()


class AccountManageDialog(QDialog):
    """账户管理列表：展示全部账户（含初始余额、状态与交易数）。"""

    def __init__(self, catalog_service: CatalogService, parent=None) -> None:
        super().__init__(parent)
        self._catalog = catalog_service
        self._entities: list[AccountInfo] = []
        self.setWindowTitle("账户管理")
        self.resize(600, 420)

        self.table = EntityTable(("名称", "描述", "初始余额", "状态", "交易数"))

        self.add_button = QPushButton("新增")
        self.edit_button = QPushButton("编辑")
        self.toggle_button = QPushButton("停用")
        self.delete_button = QPushButton("删除")
        self.delete_button.setObjectName("dangerButton")
        self.up_button = QPushButton("↑")
        self.up_button.setToolTip("上移（决定记账下拉框中的顺序）")
        self.down_button = QPushButton("↓")
        self.down_button.setToolTip("下移")
        self.close_button = QPushButton("关闭")
        self.add_button.clicked.connect(self._on_add)
        self.edit_button.clicked.connect(self._on_edit)
        self.toggle_button.clicked.connect(self._on_toggle)
        self.delete_button.clicked.connect(self._on_delete)
        self.up_button.clicked.connect(lambda: self._on_move("up"))
        self.down_button.clicked.connect(lambda: self._on_move("down"))
        self.close_button.clicked.connect(self.accept)

        button_row = QHBoxLayout()
        button_row.addWidget(self.add_button)
        button_row.addWidget(self.edit_button)
        button_row.addWidget(self.toggle_button)
        button_row.addWidget(self.delete_button)
        button_row.addWidget(self.up_button)
        button_row.addWidget(self.down_button)
        button_row.addStretch(1)
        button_row.addWidget(self.close_button)

        layout = QVBoxLayout(self)
        layout.addLayout(button_row)
        layout.addWidget(self.table)

        self.table.itemSelectionChanged.connect(self._update_buttons)
        self.refresh()

    def refresh(self) -> None:
        self._entities = self._catalog.list_all_accounts()
        self.table.load(
            [
                (
                    a.id,
                    [
                        a.name,
                        a.description,
                        format_money(a.initial_balance),
                        "启用" if a.is_active else "停用",
                        str(a.transaction_count),
                    ],
                )
                for a in self._entities
            ]
        )
        self._update_buttons()

    def _selected(self) -> AccountInfo | None:
        entity_id = self.table.selected_id()
        for entity in self._entities:
            if entity.id == entity_id:
                return entity
        return None

    def _update_buttons(self) -> None:
        entity = self._selected()
        has_selection = entity is not None
        self.edit_button.setEnabled(has_selection)
        self.toggle_button.setEnabled(has_selection)
        # 仅已停用的账户可删除（二次确认在 _on_delete）
        self.delete_button.setEnabled(has_selection and not entity.is_active)
        self.up_button.setEnabled(has_selection)
        self.down_button.setEnabled(has_selection)
        if has_selection:
            self.toggle_button.setText("停用" if entity.is_active else "启用")

    def _on_move(self, direction: str) -> None:
        entity = self._selected()
        if entity is None:
            return
        try:
            self._catalog.move_account(entity.id, direction)
        except NotFoundError as exc:
            QMessageBox.information(self, "提示", str(exc))
        except Exception:
            logger.exception("移动账户失败")
            QMessageBox.critical(self, "错误", "操作失败，请查看日志。")
        self.refresh()
        for row in range(self.table.rowCount()):
            if self.table.item(row, 0).data(Qt.UserRole) == entity.id:
                self.table.selectRow(row)
                break

    def _on_add(self) -> None:
        dialog = AccountEditorDialog(self._catalog, self)
        if dialog.exec() == QDialog.Accepted:
            self.refresh()

    def _on_edit(self) -> None:
        entity = self._selected()
        if entity is None:
            return
        dialog = AccountEditorDialog(self._catalog, self, entity)
        if dialog.exec() == QDialog.Accepted:
            self.refresh()

    def _on_toggle(self) -> None:
        entity = self._selected()
        if entity is None:
            return
        try:
            self._catalog.set_account_active(entity.id, not entity.is_active)
        except NotFoundError as exc:
            QMessageBox.information(self, "提示", str(exc))
        except Exception:
            logger.exception("切换账户状态失败")
            QMessageBox.critical(self, "错误", "操作失败，请查看日志。")
        self.refresh()

    def _on_delete(self) -> None:
        entity = self._selected()
        if entity is None:
            return
        message = (
            f"确定删除账户「{entity.name}」吗？\n\n"
            f"该账户有 {entity.transaction_count} 笔历史交易。\n"
            f"删除后这些交易仍会保留，但不再关联该账户。\n"
            f"此操作不可恢复！"
        )
        box = QMessageBox(QMessageBox.Warning, "确认删除", message, parent=self)
        cancel = box.addButton("取消", QMessageBox.RejectRole)
        confirm = box.addButton("删除", QMessageBox.DestructiveRole)
        box.setDefaultButton(cancel)
        box.exec()
        if box.clickedButton() is not confirm:
            return
        try:
            self._catalog.delete_account(entity.id)
        except NotFoundError as exc:
            QMessageBox.information(self, "提示", str(exc))
        except ValidationError as exc:
            QMessageBox.warning(self, "无法删除", str(exc))
        except Exception:
            logger.exception("删除账户失败")
            QMessageBox.critical(self, "错误", "删除失败，请查看日志。")
        self.refresh()
