"""模态弹窗交互流测试（pytest-qt，需求 §50 UI Smoke 补强）。

覆盖此前无法自动化的路径：编辑弹窗保存、删除二次确认（取消/确认）、
管理弹窗新增流程。
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import date
from decimal import Decimal

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication, QDialogButtonBox

from helpers import create_kwargs
from services.catalog_service import CatalogService
from services.transaction_service import TransactionService


def test_transaction_edit_dialog_save_flow(qtbot, seeded_factory):
    """编辑弹窗：改金额与备注 → 点保存 → 服务层数据更新、弹窗关闭。"""
    tx_service = TransactionService(session_factory=seeded_factory)
    catalog = CatalogService(session_factory=seeded_factory)
    tx_id = tx_service.create(**create_kwargs(seeded_factory))
    record = tx_service.get(tx_id)

    from ui.dialogs.transaction_dialog import TransactionDialog

    dialog = TransactionDialog(catalog, tx_service, record)
    qtbot.addWidget(dialog)
    dialog.show()

    dialog._form.amount_edit.setText("99.99")
    dialog._form.note_edit.setText("弹窗改的")
    box = dialog.findChild(QDialogButtonBox)
    qtbot.mouseClick(box.button(QDialogButtonBox.Save), Qt.LeftButton)

    updated = tx_service.get(tx_id)
    assert updated.amount == Decimal("99.99")
    assert updated.note == "弹窗改的"
    assert dialog.result() == 1  # QDialog.Accepted


def test_delete_confirmation_cancel_keeps_transaction(qtbot, seeded_factory):
    """删除二次确认：点「取消」→ 交易保留（需求 §8）。"""
    tx_service = TransactionService(session_factory=seeded_factory)
    catalog = CatalogService(session_factory=seeded_factory)
    tx_id = tx_service.create(**create_kwargs(seeded_factory))

    from ui.history_panel import HistoryPanel

    panel = HistoryPanel(catalog, tx_service)
    qtbot.addWidget(panel)
    panel.refresh()
    panel.table.selectRow(0)

    def click_cancel():
        box = QApplication.activeModalWidget()
        for button in box.buttons():
            if button.text() == "取消":
                button.click()
                return

    QTimer.singleShot(0, click_cancel)
    panel.delete_selected()

    assert tx_service.get(tx_id) is not None


def test_delete_confirmation_confirm_deletes(qtbot, seeded_factory):
    """删除二次确认：点「删除」→ 交易删除。"""
    tx_service = TransactionService(session_factory=seeded_factory)
    catalog = CatalogService(session_factory=seeded_factory)
    tx_id = tx_service.create(**create_kwargs(seeded_factory))

    from ui.history_panel import HistoryPanel

    panel = HistoryPanel(catalog, tx_service)
    qtbot.addWidget(panel)
    panel.refresh()
    panel.table.selectRow(0)

    def click_confirm():
        box = QApplication.activeModalWidget()
        for button in box.buttons():
            if button.text() == "删除":
                button.click()
                return

    QTimer.singleShot(0, click_confirm)
    panel.delete_selected()

    assert tx_service.get(tx_id) is None


def test_channel_manage_add_flow(qtbot, seeded_factory):
    """管理弹窗：点「新增」→ 填名称 → 点保存 → 渠道创建。"""
    catalog = CatalogService(session_factory=seeded_factory)

    from ui.dialogs.channel_manage_dialog import ChannelManageDialog

    dialog = ChannelManageDialog(catalog)
    qtbot.addWidget(dialog)
    dialog.show()

    def fill_editor():
        editor = QApplication.activeModalWidget()
        editor.name_edit.setText("新渠道")
        box = editor.findChild(QDialogButtonBox)
        box.button(QDialogButtonBox.Save).click()

    QTimer.singleShot(0, fill_editor)
    dialog._on_add()

    assert "新渠道" in {c.name for c in catalog.list_all_channels()}
    dialog.close()


def test_history_panel_shows_deleted_reference(qtbot, seeded_factory):
    """软外键：实体删除后历史表格显示「已删除」而非崩溃。"""
    tx_service = TransactionService(session_factory=seeded_factory)
    catalog = CatalogService(session_factory=seeded_factory)
    tx_id = tx_service.create(**create_kwargs(seeded_factory))

    from sqlalchemy import select

    from database.models import Channel

    with seeded_factory() as session:
        record = tx_service.get(tx_id)
        session.delete(session.get(Channel, record.channel_id))
        session.commit()

    from ui.history_panel import HistoryPanel

    panel = HistoryPanel(catalog, tx_service)
    qtbot.addWidget(panel)
    panel.refresh()

    assert panel.table.rowCount() == 1
    assert panel.table.item(0, 3).text() == "（已删除）"


def test_filter_dialog_apply_flow(qtbot, seeded_factory):
    """筛选弹窗：设置类型 + 日期范围 → 应用 → filters() 返回对应条件。"""
    catalog = CatalogService(session_factory=seeded_factory)

    from ui.dialogs.filter_dialog import FilterDialog

    dialog = FilterDialog(catalog)
    qtbot.addWidget(dialog)
    dialog.show()

    dialog.type_combo.setCurrentIndex(dialog.type_combo.findData("expense"))
    dialog.date_from_check.setChecked(True)
    dialog.apply_button.click()

    filters = dialog.filters()
    assert filters["type"] == "expense"
    assert "date_from" in filters
    assert "date_to" not in filters


def test_filter_dialog_clear_flow(qtbot, seeded_factory):
    catalog = CatalogService(session_factory=seeded_factory)

    from ui.dialogs.filter_dialog import FilterDialog

    dialog = FilterDialog(catalog, current={"type": "expense"})
    qtbot.addWidget(dialog)
    dialog.show()
    assert dialog.type_combo.currentData() == "expense"  # 回填

    dialog.clear_button.click()
    assert dialog.filters() == {}


def test_sort_dialog_multi_level_flow(qtbot):
    from ui.dialogs.sort_dialog import SortDialog

    dialog = SortDialog(current=[("type", "asc")])
    qtbot.addWidget(dialog)
    dialog.show()

    # 第 1 级：类型升序（回填验证）
    row1_field, row1_dir = dialog._rows[0]
    assert row1_field.currentData() == "type"
    assert row1_dir.currentData() == "asc"
    # 第 2 级：金额降序
    row2_field, row2_dir = dialog._rows[1]
    row2_field.setCurrentIndex(row2_field.findData("amount"))
    row2_dir.setCurrentIndex(row2_dir.findData("desc"))
    dialog.apply_button.click()

    assert dialog.sort() == [("type", "asc"), ("amount", "desc")]


def test_sort_dialog_default_flow(qtbot):
    from ui.dialogs.sort_dialog import SortDialog

    dialog = SortDialog(current=[("amount", "desc")])
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.default_button.click()
    assert dialog.sort() == [("date", "desc")]


def test_channel_manage_move_up_flow(qtbot, seeded_factory):
    """管理弹窗：选中 Salary → 点 ↑ → 顺序上移一位且保持选中。"""
    catalog = CatalogService(session_factory=seeded_factory)

    from ui.dialogs.channel_manage_dialog import ChannelManageDialog

    dialog = ChannelManageDialog(catalog)
    qtbot.addWidget(dialog)
    dialog.show()
    for row in range(dialog.table.rowCount()):
        if dialog.table.item(row, 0).text() == "Salary":
            dialog.table.selectRow(row)
            break
    assert dialog.up_button.isEnabled()

    before = [c.name for c in catalog.list_active_channels()]
    qtbot.mouseClick(dialog.up_button, Qt.LeftButton)
    after = [c.name for c in catalog.list_active_channels()]
    assert after[before.index("Salary") - 1] == "Salary"
    dialog.close()


def test_channel_delete_confirm_flow(qtbot, seeded_factory):
    """管理弹窗删除流（用户反馈）：停用渠道 → 删除按钮可用 → 二次确认 → 删除。"""
    catalog = CatalogService(session_factory=seeded_factory)
    salary = next(c for c in catalog.list_all_channels() if c.name == "Salary")
    catalog.set_channel_active(salary.id, False)

    from ui.dialogs.channel_manage_dialog import ChannelManageDialog

    dialog = ChannelManageDialog(catalog)
    qtbot.addWidget(dialog)
    dialog.show()
    for row in range(dialog.table.rowCount()):
        if dialog.table.item(row, 0).text() == "Salary":
            dialog.table.selectRow(row)
            break
    assert dialog.delete_button.isEnabled()  # 仅停用的可删除

    def click_confirm():
        box = QApplication.activeModalWidget()
        for button in box.buttons():
            if button.text() == "删除":
                button.click()
                return

    QTimer.singleShot(0, click_confirm)
    dialog._on_delete()

    assert "Salary" not in {c.name for c in catalog.list_all_channels()}
    dialog.close()
