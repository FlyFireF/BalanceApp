"""分类管理弹窗：新增 / 编辑 / 停用（启用）。类型不可修改；Other 不可停用。"""

from __future__ import annotations

import logging

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from database.models import CategoryType
from services.catalog_service import CatalogService
from services.dto import CategoryInfo
from services.exceptions import NotFoundError, ValidationError
from ui.widgets.entity_table import EntityTable

logger = logging.getLogger(__name__)

_TYPE_DISPLAY = {
    CategoryType.INCOME.value: "收入",
    CategoryType.EXPENSE.value: "支出",
}


class CategoryEditorDialog(QDialog):
    """新增/编辑分类。编辑时类型固定（类型变更会破坏历史统计一致性）。"""

    def __init__(
        self,
        catalog_service: CatalogService,
        parent=None,
        category: CategoryInfo | None = None,
    ) -> None:
        super().__init__(parent)
        self._catalog = catalog_service
        self._category = category
        self.setWindowTitle("新增分类" if category is None else f"编辑分类：{category.name}")

        self.name_edit = QLineEdit()
        self.name_edit.setMaxLength(50)
        self.name_edit.setPlaceholderText("分类名称，如 餐饮")

        self.type_combo = QComboBox()
        self.type_combo.addItem("收入", CategoryType.INCOME.value)
        self.type_combo.addItem("支出", CategoryType.EXPENSE.value)

        self.desc_edit = QLineEdit()
        self.desc_edit.setMaxLength(200)
        self.desc_edit.setPlaceholderText("描述（可选）")

        if category is not None:
            self.name_edit.setText(category.name)
            self.desc_edit.setText(category.description)
            self.type_combo.setCurrentIndex(
                0 if category.type == CategoryType.INCOME.value else 1
            )
            self.type_combo.setEnabled(False)  # 类型不可修改

        form = QFormLayout()
        form.addRow("名称", self.name_edit)
        form.addRow("类型", self.type_combo)
        form.addRow("描述", self.desc_edit)

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
            if self._category is None:
                self._catalog.create_category(
                    self.name_edit.text(), self.type_combo.currentData(), self.desc_edit.text()
                )
            else:
                self._catalog.update_category(
                    self._category.id, self.name_edit.text(), self.desc_edit.text()
                )
        except ValidationError as exc:
            QMessageBox.warning(self, "无法保存", str(exc))
            return
        except Exception:
            logger.exception("保存分类失败")
            QMessageBox.critical(self, "错误", "保存失败，请查看日志。")
            return
        self.accept()


class CategoryManageDialog(QDialog):
    """分类管理列表：展示全部分类（含类型、状态与交易数）。"""

    def __init__(self, catalog_service: CatalogService, parent=None) -> None:
        super().__init__(parent)
        self._catalog = catalog_service
        self._entities: list[CategoryInfo] = []
        self.setWindowTitle("分类管理")
        self.resize(600, 460)

        self.table = EntityTable(("名称", "类型", "描述", "状态", "交易数"))

        self.add_button = QPushButton("新增")
        self.edit_button = QPushButton("编辑")
        self.toggle_button = QPushButton("停用")
        self.delete_button = QPushButton("删除")
        self.delete_button.setObjectName("dangerButton")
        self.close_button = QPushButton("关闭")
        self.add_button.clicked.connect(self._on_add)
        self.edit_button.clicked.connect(self._on_edit)
        self.toggle_button.clicked.connect(self._on_toggle)
        self.delete_button.clicked.connect(self._on_delete)
        self.close_button.clicked.connect(self.accept)

        button_row = QHBoxLayout()
        button_row.addWidget(self.add_button)
        button_row.addWidget(self.edit_button)
        button_row.addWidget(self.toggle_button)
        button_row.addWidget(self.delete_button)
        button_row.addStretch(1)
        button_row.addWidget(self.close_button)

        layout = QVBoxLayout(self)
        layout.addLayout(button_row)
        layout.addWidget(self.table)

        self.table.itemSelectionChanged.connect(self._update_buttons)
        self.refresh()

    def refresh(self) -> None:
        self._entities = self._catalog.list_all_categories()
        self.table.load(
            [
                (
                    c.id,
                    [
                        c.name,
                        _TYPE_DISPLAY.get(c.type, c.type),
                        c.description,
                        "启用" if c.is_active else "停用",
                        str(c.transaction_count),
                    ],
                )
                for c in self._entities
            ]
        )
        self._update_buttons()

    def _selected(self) -> CategoryInfo | None:
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
        # 仅已停用的分类可删除（Other 在服务层保护；二次确认在 _on_delete）
        self.delete_button.setEnabled(has_selection and not entity.is_active)
        if has_selection:
            self.toggle_button.setText("停用" if entity.is_active else "启用")

    def _on_add(self) -> None:
        dialog = CategoryEditorDialog(self._catalog, self)
        if dialog.exec() == QDialog.Accepted:
            self.refresh()

    def _on_edit(self) -> None:
        entity = self._selected()
        if entity is None:
            return
        dialog = CategoryEditorDialog(self._catalog, self, entity)
        if dialog.exec() == QDialog.Accepted:
            self.refresh()

    def _on_toggle(self) -> None:
        entity = self._selected()
        if entity is None:
            return
        try:
            self._catalog.set_category_active(entity.id, not entity.is_active)
        except ValidationError as exc:  # 例如停用 Other
            QMessageBox.warning(self, "无法操作", str(exc))
        except NotFoundError as exc:
            QMessageBox.information(self, "提示", str(exc))
        except Exception:
            logger.exception("切换分类状态失败")
            QMessageBox.critical(self, "错误", "操作失败，请查看日志。")
        self.refresh()

    def _on_delete(self) -> None:
        entity = self._selected()
        if entity is None:
            return
        message = (
            f"确定删除分类「{entity.name}」吗？\n\n"
            f"该分类有 {entity.transaction_count} 笔历史交易。\n"
            f"删除后这些交易仍会保留，但不再关联该分类。\n"
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
            self._catalog.delete_category(entity.id)
        except ValidationError as exc:  # 例如删除 Other
            QMessageBox.warning(self, "无法删除", str(exc))
        except NotFoundError as exc:
            QMessageBox.information(self, "提示", str(exc))
        except Exception:
            logger.exception("删除分类失败")
            QMessageBox.critical(self, "错误", "删除失败，请查看日志。")
        self.refresh()
