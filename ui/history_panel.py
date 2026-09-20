"""历史记录面板：表格展示、编辑、删除（删除二次确认，需求 §8/§12）。"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from services.dto import TransactionRecord
from services.exceptions import NotFoundError
from services.transaction_service import TransactionService
from ui import theme
from ui.dialogs.filter_dialog import FilterDialog
from ui.dialogs.sort_dialog import SortDialog
from ui.dialogs.transaction_dialog import TransactionDialog
from utils.currency import format_money

logger = logging.getLogger(__name__)

_COLUMNS = ("日期", "类型", "金额", "渠道", "账户", "分类", "备注", "标签")


class HistoryPanel(QFrame):
    """历史记录表格卡片。编辑/删除后发出 data_changed 信号。"""

    data_changed = Signal()

    def __init__(
        self,
        catalog_service,
        transaction_service: TransactionService,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self._catalog_service = catalog_service
        self._transaction_service = transaction_service
        self._records: list[TransactionRecord] = []
        self._total = 0
        self._page = 1
        self._page_size = 50
        self._sort: list[tuple[str, str]] = [("date", "desc")]
        self._filters: dict = {}

        title = QLabel("历史记录")
        title.setObjectName("cardTitle")
        self.count_label = QLabel("共 0 条")

        # 搜索框（需求 §13）：实时过滤，空则显示全部；搜索变化回到第 1 页
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("搜索金额 / 备注 / 渠道 / 账户 / 分类…")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setMaximumWidth(300)
        self.search_edit.textChanged.connect(self._on_search_changed)

        # 筛选 / 排序（用户反馈）：与搜索、翻页组合生效
        self.filter_button = QPushButton("筛选")
        self.sort_button = QPushButton("排序")
        self.filter_button.clicked.connect(self._open_filter_dialog)
        self.sort_button.clicked.connect(self._open_sort_dialog)

        self.edit_button = QPushButton("编辑")
        self.delete_button = QPushButton("删除")
        self.edit_button.setEnabled(False)
        self.delete_button.setEnabled(False)
        self.edit_button.clicked.connect(self.edit_selected)
        self.delete_button.clicked.connect(self.delete_selected)

        header_row = QHBoxLayout()
        header_row.addWidget(title)
        header_row.addSpacing(16)
        header_row.addWidget(self.search_edit)
        header_row.addWidget(self.filter_button)
        header_row.addWidget(self.sort_button)
        header_row.addStretch(1)
        header_row.addWidget(self.count_label)
        header_row.addWidget(self.edit_button)
        header_row.addWidget(self.delete_button)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(32)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)  # 日期
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)  # 金额
        header.setSectionResizeMode(QHeaderView.Stretch)
        self.table.setAlternatingRowColors(True)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self.table.itemDoubleClicked.connect(lambda _item: self.edit_selected())

        # 分页栏（翻页 + 每页条数 10/20/50/100）
        self.prev_button = QPushButton("上一页")
        self.next_button = QPushButton("下一页")
        self.page_label = QLabel("第 1 / 1 页")
        self.page_size_combo = QComboBox()
        for size in (10, 20, 50, 100):
            self.page_size_combo.addItem(f"{size} 条/页", size)
        self.page_size_combo.setCurrentIndex(2)  # 默认 50
        self.prev_button.clicked.connect(self._prev_page)
        self.next_button.clicked.connect(self._next_page)
        self.page_size_combo.currentIndexChanged.connect(self._on_page_size_changed)

        pagination_row = QHBoxLayout()
        pagination_row.addWidget(self.prev_button)
        pagination_row.addWidget(self.page_label)
        pagination_row.addWidget(self.next_button)
        pagination_row.addStretch(1)
        pagination_row.addWidget(QLabel("每页"))
        pagination_row.addWidget(self.page_size_combo)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.addLayout(header_row)
        layout.addWidget(self.table)
        layout.addLayout(pagination_row)

    # ---------- 对外方法 ----------

    def refresh(self) -> None:
        """重新加载当前页。搜索关键词、筛选条件、多级排序组合生效。"""
        keyword = self.search_edit.text().strip() or None
        page = self._transaction_service.list_transactions_page(
            keyword=keyword,
            filters=self._filters,
            sort=self._sort,
            page=self._page,
            page_size=self._page_size,
        )
        self._total = page.total
        self._records = page.records
        if self._page > page.pages:
            # 删除后当前页越界：回到最后一页
            self._page = page.pages
            self.refresh()
            return
        self.table.setRowCount(len(self._records))
        for row, record in enumerate(self._records):
            self._fill_row(row, record)
        has_query = bool(keyword or self._filters)
        self.count_label.setText(f"{'找到' if has_query else '共'} {self._total} 条")
        self.page_label.setText(f"第 {self._page} / {page.pages} 页")
        self.prev_button.setEnabled(self._page > 1)
        self.next_button.setEnabled(self._page < page.pages)

    def focus_search(self) -> None:
        """聚焦搜索框并全选（Ctrl+F，需求 §14）。"""
        self.search_edit.setFocus()
        self.search_edit.selectAll()

    def clear_search(self) -> None:
        """清空搜索（Esc，需求 §14）；textChanged 会自动触发刷新。"""
        if self.search_edit.text():
            self.search_edit.clear()

    # ---------- 分页 ----------

    def _on_search_changed(self) -> None:
        self._page = 1
        self.refresh()

    def _prev_page(self) -> None:
        if self._page > 1:
            self._page -= 1
            self.refresh()

    def _next_page(self) -> None:
        self._page += 1
        self.refresh()  # refresh 内部会做越界回退

    def _on_page_size_changed(self) -> None:
        self._page_size = int(self.page_size_combo.currentData())
        self._page = 1
        self.refresh()

    # ---------- 筛选 / 排序 ----------

    def _open_filter_dialog(self) -> None:
        dialog = FilterDialog(self._catalog_service, self._filters, self)
        if dialog.exec() == QDialog.Accepted:
            self._filters = dialog.filters()
            self._page = 1
            self.refresh()
            self._update_filter_button()

    def _open_sort_dialog(self) -> None:
        dialog = SortDialog(self._sort, self)
        if dialog.exec() == QDialog.Accepted:
            self._sort = dialog.sort()
            self._page = 1
            self.refresh()
            self._update_sort_button()

    def _update_filter_button(self) -> None:
        count = len(self._filters)
        self.filter_button.setText(f"筛选 ({count})" if count else "筛选")

    def _update_sort_button(self) -> None:
        custom = self._sort != [("date", "desc")]
        self.sort_button.setText("排序 · 自定义" if custom else "排序")

    # ---------- 编辑 / 删除 ----------

    def edit_selected(self) -> None:
        """弹窗编辑当前选中交易；保存成功后刷新。"""
        record = self._selected_record()
        if record is None:
            return
        dialog = TransactionDialog(self._catalog_service, self._transaction_service, record, self)
        if dialog.exec() == QDialog.Accepted:
            self.refresh()
            self.data_changed.emit()

    def delete_selected(self) -> None:
        """删除当前选中交易（必须先通过二次确认）。"""
        record = self._selected_record()
        if record is None:
            return
        if not self._confirm_delete(record):
            return
        try:
            self._transaction_service.delete(record.id)
        except NotFoundError as exc:
            QMessageBox.information(self, "提示", str(exc))
            self.refresh()
            return
        except Exception:
            logger.exception("删除交易失败")
            QMessageBox.critical(self, "错误", "删除失败，请查看日志。")
            return
        self.refresh()
        self.data_changed.emit()

    def _confirm_delete(self, record: TransactionRecord) -> bool:
        """删除二次确认（需求 §8）：展示金额/分类/日期，[取消][删除]。"""
        kind = "收入" if record.type == "income" else "支出"
        message = (
            f"确定删除这笔{kind}吗？\n\n"
            f"金额：{format_money(record.amount)}\n"
            f"分类：{record.category_name or '（已删除）'}\n"
            f"日期：{record.date}"
        )
        box = QMessageBox(QMessageBox.Question, "确认删除", message, parent=self)
        cancel = box.addButton("取消", QMessageBox.RejectRole)
        confirm = box.addButton("删除", QMessageBox.DestructiveRole)
        box.setDefaultButton(cancel)  # 默认焦点在「取消」，防止误删
        box.exec()
        return box.clickedButton() is confirm

    # ---------- 内部 ----------

    def _fill_row(self, row: int, record: TransactionRecord) -> None:
        is_income = record.type == "income"
        type_text = "收入" if is_income else "支出"
        amount_text = ("+" if is_income else "-") + format_money(record.amount)
        # 金额颜色随主题（深色下使用更亮的绿/红）
        amount_color = QColor(theme.color("green" if is_income else "red"))

        values = (
            record.date.isoformat(),
            type_text,
            amount_text,
            record.channel_name or "（已删除）",
            record.account_name or "（已删除）",
            record.category_name or "（已删除）",
            record.note,
            record.tags,
        )
        for column, value in enumerate(values):
            item = QTableWidgetItem(value)
            item.setTextAlignment(
                Qt.AlignVCenter | (Qt.AlignRight if column == 2 else Qt.AlignLeft)
            )
            if column == 2:
                item.setForeground(amount_color)
                font = item.font()
                font.setBold(True)
                item.setFont(font)
            self.table.setItem(row, column, item)

    def _selected_record(self) -> TransactionRecord | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        index = rows[0].row()
        if index < 0 or index >= len(self._records):
            return None
        return self._records[index]

    def _on_selection_changed(self) -> None:
        has_selection = self._selected_record() is not None
        self.edit_button.setEnabled(has_selection)
        self.delete_button.setEnabled(has_selection)
