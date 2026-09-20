"""主窗口：三栏布局（需求 §9）。

┌──────────┬─────────────────────┬──────────────────────┐
│ 左侧导航  │ 记账面板（上）        │ 右侧 Dashboard        │
│          │ 历史记录（下）        │                      │
└──────────┴─────────────────────┴──────────────────────┘

数据联动（需求 §39）：记账保存 / 历史编辑删除 / 管理弹窗关闭 → 相关面板自动刷新。
"""

from __future__ import annotations

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QMainWindow,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from config import settings
from services.backup_service import BackupService
from services.catalog_service import CatalogService
from services.export_service import ExportService
from services.import_service import ImportService
from services.statistics_service import StatisticsService
from services.transaction_service import TransactionService
from ui.bookkeeping_panel import BookkeepingPanel
from ui.dashboard import DashboardPanel
from ui.dialogs.account_manage_dialog import AccountManageDialog
from ui.dialogs.category_manage_dialog import CategoryManageDialog
from ui.dialogs.channel_manage_dialog import ChannelManageDialog
from ui.dialogs.data_manage_dialog import DataManageDialog
from ui.dialogs.settings_dialog import SettingsDialog
from ui.history_panel import HistoryPanel
from ui.sidebar import Sidebar
from ui.theme import THEME_SYSTEM, ThemeManager, current_theme


class MainWindow(QMainWindow):
    """应用主窗口（三栏）。"""

    def __init__(
        self,
        catalog_service: CatalogService,
        transaction_service: TransactionService,
        statistics_service: StatisticsService,
        import_service: ImportService,
        export_service: ExportService,
        backup_service: BackupService,
        theme_manager: ThemeManager,
    ) -> None:
        super().__init__()
        self.setWindowTitle(settings.APP_NAME)
        self._catalog_service = catalog_service
        self._import_service = import_service
        self._export_service = export_service
        self._backup_service = backup_service
        self._theme_manager = theme_manager

        self.sidebar = Sidebar()
        self.bookkeeping_panel = BookkeepingPanel(catalog_service, transaction_service)
        self.history_panel = HistoryPanel(catalog_service, transaction_service)
        self.dashboard_panel = DashboardPanel(statistics_service)
        self.dashboard_panel.setFixedWidth(400)

        # 中间栏：记账（上）+ 历史记录（下）
        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(self.bookkeeping_panel)
        splitter.addWidget(self.history_panel)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)
        splitter.setSizes([290, 430])

        middle = QWidget()
        middle_layout = QVBoxLayout(middle)
        middle_layout.setContentsMargins(0, 0, 0, 0)
        middle_layout.addWidget(splitter)

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)
        layout.addWidget(self.sidebar)
        layout.addWidget(middle, 1)
        layout.addWidget(self.dashboard_panel)
        self.setCentralWidget(central)

        # 导航
        self.sidebar.nav_clicked.connect(self._on_nav)

        # 数据联动（需求 §39）
        self.bookkeeping_panel.transaction_saved.connect(self._on_transactions_changed)
        self.history_panel.data_changed.connect(self.dashboard_panel.refresh)

        # 快捷键（需求 §14）：Ctrl+F / Esc / Delete
        self._shortcut_search = QShortcut(QKeySequence("Ctrl+F"), self)
        self._shortcut_search.activated.connect(self.history_panel.focus_search)
        self._shortcut_esc = QShortcut(QKeySequence(Qt.Key_Escape), self)
        self._shortcut_esc.activated.connect(self._on_esc_shortcut)
        self._shortcut_delete = QShortcut(QKeySequence(Qt.Key_Delete), self)
        self._shortcut_delete.activated.connect(self._on_delete_shortcut)

        # 跟随系统主题：运行中监听系统明暗变化（用户反馈：切换系统颜色需同步）
        self._theme_timer = QTimer(self)
        self._theme_timer.setInterval(3000)
        self._theme_timer.timeout.connect(self._sync_system_theme)
        self._theme_timer.start()

        self.resize(1280, 780)
        self.setMinimumSize(1080, 620)

        self.history_panel.refresh()

    # ---------- 内部 ----------

    def _on_transactions_changed(self) -> None:
        self.history_panel.refresh()
        self.dashboard_panel.refresh()

    def _on_nav(self, key: str) -> None:
        if key == "bookkeeping":
            self.sidebar.bookkeeping_button.setChecked(True)
            self.bookkeeping_panel.form.amount_edit.setFocus()
        elif key == "dashboard":
            visible = not self.dashboard_panel.isVisible()
            self.dashboard_panel.setVisible(visible)
            self.sidebar.dashboard_button.setChecked(visible)
        elif key == "channels":
            self._open_manager(ChannelManageDialog)
        elif key == "accounts":
            self._open_manager(AccountManageDialog)
        elif key == "categories":
            self._open_manager(CategoryManageDialog)
        elif key == "data":
            dialog = DataManageDialog(self._import_service, self._export_service, self)
            dialog.imported.connect(self._on_data_imported)
            dialog.exec()
        elif key == "settings":
            dialog = SettingsDialog(self._backup_service, self._theme_manager, self)
            dialog.exec()

    def _on_data_imported(self) -> None:
        """导入成功后全局刷新（需求 §39）。"""
        self.bookkeeping_panel.form.reload_options()
        self.history_panel.refresh()
        self.dashboard_panel.refresh()

    def _open_manager(self, dialog_class) -> None:
        """打开管理弹窗；关闭后刷新表单选项、历史记录与 Dashboard（需求 §39）。"""
        dialog = dialog_class(self._catalog_service, self)
        dialog.exec()
        self.bookkeeping_panel.form.reload_options()
        self.history_panel.refresh()
        self.dashboard_panel.refresh()

    # ---------- 主题跟随系统（用户反馈）----------

    def _sync_system_theme(self) -> None:
        """「跟随系统」模式下，系统明暗变化时同步应用主题（约每 3 秒检查）。"""
        if self._theme_manager.get_mode() != THEME_SYSTEM:
            return
        app = QApplication.instance()
        if app is None:
            return
        effective = self._theme_manager.effective_theme(THEME_SYSTEM)
        if effective != current_theme():
            ThemeManager.apply(app, effective)

    # ---------- 快捷键处理（需求 §14）----------

    def _table_has_focus(self) -> bool:
        focus = QApplication.focusWidget()
        table = self.history_panel.table
        return focus is table or focus is table.viewport()

    def _on_delete_shortcut(self) -> None:
        """Delete：删除当前选中的历史记录。

        焦点守卫：仅当焦点在历史表格上时生效，避免在输入框里打字时误删；
        删除本身仍有二次确认（需求 §8）。
        """
        if self._table_has_focus():
            self.history_panel.delete_selected()

    def _on_esc_shortcut(self) -> None:
        """Esc：取消当前编辑状态。优先级：
        ① 清空搜索 → ② 取消表格选中 → ③ 清空记账表单输入。
        打开的弹窗由 Qt 原生 Esc 关闭（所有 QDialog 默认行为）。"""
        history = self.history_panel
        if history.search_edit.text():
            history.clear_search()
            return
        if self._table_has_focus() and history.table.selectedItems():
            history.table.clearSelection()
            return
        form = self.bookkeeping_panel.form
        focus = QApplication.focusWidget()
        editing_bookkeeping = focus in (
            form.amount_edit,
            form.note_edit,
            form.tags_edit,
        )
        if editing_bookkeeping and (
            form.amount_edit.text() or form.note_edit.text() or form.tags_edit.text()
        ):
            form.reset_after_save()
