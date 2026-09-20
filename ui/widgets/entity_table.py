"""管理页通用只读表格：实体 id 存入 UserRole，支持按选中行取 id。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
)


class EntityTable(QTableWidget):
    """渠道/账户/分类管理弹窗共用的实体列表表格。"""

    def __init__(self, columns: tuple[str, ...], parent=None) -> None:
        super().__init__(0, len(columns), parent)
        self.setHorizontalHeaderLabels(columns)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(30)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.setAlternatingRowColors(True)

    def load(self, rows: list[tuple[int, list[str]]]) -> None:
        """rows: [(实体 id, [列文本...]), ...]，id 存入每个单元格的 UserRole。"""
        self.setRowCount(len(rows))
        for row, (entity_id, values) in enumerate(rows):
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, entity_id)
                item.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)
                self.setItem(row, column, item)

    def selected_id(self) -> int | None:
        """当前选中行的实体 id；无选中返回 None。"""
        rows = self.selectionModel().selectedRows()
        if not rows:
            return None
        item = self.item(rows[0].row(), 0)
        return int(item.data(Qt.UserRole)) if item else None
