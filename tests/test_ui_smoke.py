"""UI 冒烟测试：确认 PySide6 / QtCharts 安装正常、窗口可创建。

使用 offscreen 平台，不需要真实显示器。
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QLabel

from database.models import Account, Category, Channel
from helpers import EXPENSE, INCOME, entity_id, seed_official_scenario
from services.backup_service import BackupService
from services.export_service import ExportService
from services.import_service import ImportService
from services.statistics_service import StatisticsService


def test_qt_widgets_create_window():
    from PySide6.QtWidgets import QApplication, QLabel, QMainWindow

    app = QApplication.instance() or QApplication([])
    window = QMainWindow()
    window.setWindowTitle("Money Manager")
    window.setCentralWidget(QLabel("smoke test"))
    window.show()
    app.processEvents()
    assert window.isVisible()
    window.close()
    app.processEvents()


def test_qtcharts_importable():
    import PySide6.QtCharts  # noqa: F401


# ---------- 面板冒烟 ----------


def _make_panel_services(seeded_factory):
    """为面板测试构建绑定临时库的服务。"""
    from services.catalog_service import CatalogService
    from services.transaction_service import TransactionService

    catalog = CatalogService(session_factory=seeded_factory)
    transactions = TransactionService(session_factory=seeded_factory)
    return catalog, transactions


def test_history_panel_shows_transactions(seeded_factory):
    from datetime import date
    from decimal import Decimal

    from PySide6.QtWidgets import QApplication

    from ui.history_panel import HistoryPanel

    QApplication.instance() or QApplication([])
    catalog, tx_service = _make_panel_services(seeded_factory)
    channel_id = next(c.id for c in catalog.list_active_channels() if c.name == "Salary")
    account_id = next(a.id for a in catalog.list_active_accounts() if a.name == "Bank")
    tx_service.create(
        type="expense",
        amount=Decimal("52.00"),
        date=date(2026, 9, 18),
        channel_id=channel_id,
        account_id=account_id,
        note="午饭",
    )

    panel = HistoryPanel(catalog, tx_service)
    panel.refresh()

    assert panel.table.rowCount() == 1
    assert panel.table.item(0, 0).text() == "2026-09-18"  # 日期
    assert panel.table.item(0, 2).text() == "-¥52.00"     # 金额（支出红色负号）
    assert panel.table.item(0, 3).text() == "Salary"      # 渠道
    assert panel.table.item(0, 5).text() == "Other"       # 自动映射 Other


def test_bookkeeping_panel_save(seeded_factory):
    from decimal import Decimal

    from PySide6.QtWidgets import QApplication

    from ui.bookkeeping_panel import BookkeepingPanel

    QApplication.instance() or QApplication([])
    catalog, tx_service = _make_panel_services(seeded_factory)
    panel = BookkeepingPanel(catalog, tx_service)
    panel.form.amount_edit.setText("88.50")

    saved = []
    panel.transaction_saved.connect(lambda: saved.append(True))
    panel.save_transaction()

    assert saved
    records = tx_service.list_transactions()
    assert len(records) == 1
    assert records[0].amount == Decimal("88.50")
    assert panel.form.amount_edit.text() == ""  # 保存成功后清空金额（需求 §11）


def test_bookkeeping_panel_invalid_amount_blocked(seeded_factory, monkeypatch):
    from PySide6.QtWidgets import QApplication, QMessageBox

    from ui.bookkeeping_panel import BookkeepingPanel

    QApplication.instance() or QApplication([])
    catalog, tx_service = _make_panel_services(seeded_factory)

    warnings = []
    monkeypatch.setattr(
        QMessageBox, "warning", lambda *args, **kwargs: warnings.append(args)
    )

    panel = BookkeepingPanel(catalog, tx_service)
    panel.form.amount_edit.setText("abc")
    panel.save_transaction()

    assert len(warnings) == 1
    assert tx_service.list_transactions() == []  # 没有写入任何数据


# ---------- 管理弹窗冒烟 ----------


def test_channel_manage_dialog_refresh(seeded_factory):
    from PySide6.QtWidgets import QApplication

    from ui.dialogs.channel_manage_dialog import ChannelManageDialog

    QApplication.instance() or QApplication([])
    catalog, _ = _make_panel_services(seeded_factory)
    dialog = ChannelManageDialog(catalog)
    assert dialog.table.rowCount() == 5
    # 每月固定金额列默认 ¥0.00；删除按钮存在且默认禁用
    assert dialog.table.item(0, 2).text() == "¥0.00"
    assert dialog.delete_button is not None
    assert not dialog.delete_button.isEnabled()


def test_account_manage_dialog_refresh(seeded_factory):
    from PySide6.QtWidgets import QApplication

    from ui.dialogs.account_manage_dialog import AccountManageDialog

    QApplication.instance() or QApplication([])
    catalog, _ = _make_panel_services(seeded_factory)
    dialog = AccountManageDialog(catalog)
    assert dialog.table.rowCount() == 4
    # 初始余额列显示 ¥0.00
    assert dialog.table.item(0, 2).text() == "¥0.00"


def test_category_manage_dialog_refresh(seeded_factory):
    from PySide6.QtWidgets import QApplication

    from ui.dialogs.category_manage_dialog import CategoryManageDialog

    QApplication.instance() or QApplication([])
    catalog, _ = _make_panel_services(seeded_factory)
    dialog = CategoryManageDialog(catalog)
    assert dialog.table.rowCount() == 14


def test_main_window_constructs(seeded_factory):
    from PySide6.QtWidgets import QApplication

    from ui.main_window import MainWindow
    from ui.theme import ThemeManager

    QApplication.instance() or QApplication([])
    catalog, tx_service = _make_panel_services(seeded_factory)
    statistics = StatisticsService(session_factory=seeded_factory)
    import_svc = ImportService(session_factory=seeded_factory)
    export_svc = ExportService(session_factory=seeded_factory)
    backup_svc = BackupService(session_factory=seeded_factory)
    theme_mgr = ThemeManager(session_factory=seeded_factory)
    window = MainWindow(
        catalog, tx_service, statistics, import_svc, export_svc, backup_svc, theme_mgr
    )
    assert window.sidebar is not None
    assert window.bookkeeping_panel is not None
    assert window.history_panel is not None
    assert window.dashboard_panel is not None
    # 导航按钮齐备（需求 §10）
    assert window.sidebar.bookkeeping_button.text() == "记账"
    assert window.sidebar.dashboard_button.text() == "Dashboard"
    assert window.sidebar.channel_button is not None
    assert window.sidebar.account_button is not None
    assert window.sidebar.category_button is not None
    assert window.sidebar.data_button is not None
    assert window.sidebar.settings_button is not None
    # 标题分两行显示（用户反馈）
    title = window.sidebar.findChild(QLabel, "appTitle")
    assert "Money" in title.text() and "Manager" in title.text()
    # 仅 记账 / Dashboard 是切换型按钮，管理类入口直接开弹窗（用户反馈）
    assert window.sidebar.bookkeeping_button.isCheckable()
    assert window.sidebar.dashboard_button.isCheckable()
    assert not window.sidebar.channel_button.isCheckable()
    assert not window.sidebar.account_button.isCheckable()
    assert not window.sidebar.category_button.isCheckable()
    assert not window.sidebar.data_button.isCheckable()
    assert not window.sidebar.settings_button.isCheckable()
    window.close()


# ---------- Dashboard 冒烟 ----------


def test_dashboard_official_scenario(seeded_factory, transaction_service):
    from PySide6.QtWidgets import QApplication

    from ui.dashboard import DashboardPanel

    QApplication.instance() or QApplication([])
    seed_official_scenario(seeded_factory, transaction_service)
    statistics = StatisticsService(session_factory=seeded_factory)

    panel = DashboardPanel(statistics)
    panel.set_month(2026, 9)

    assert panel.month_label.text() == "2026年9月"
    assert panel.income_value_label.text() == "¥3,000.00"
    assert panel.expense_value_label.text() == "¥500.00"
    assert panel.net_value_label.text() == "¥2,500.00"

    salary = next(c for c in panel.channel_cards if c.stat.channel_name == "Salary")
    assert salary.percent_label.text() == "83.33%"  # 月度口径：(3000-500)/3000
    assert salary.progress.value() == 83
    assert salary.balance_label.text() == "余额 ¥6,500.00"
    assert "¥3,000.00" in salary.month_metric_label.text()  # 本月行
    assert "¥8,000.00" in salary.cum_metric_label.text()  # 累计行

    # 账户总览包含 Bank 余额（需求 §22）
    account_texts = [
        label.text() for row in panel.account_rows for label in row.findChildren(QLabel)
    ]
    assert "¥6,500.00" in account_texts
    assert panel.empty_label.isHidden()


def test_dashboard_month_switching(seeded_factory, transaction_service):
    from PySide6.QtWidgets import QApplication

    from ui.dashboard import DashboardPanel

    QApplication.instance() or QApplication([])
    seed_official_scenario(seeded_factory, transaction_service)
    panel = DashboardPanel(StatisticsService(session_factory=seeded_factory))
    panel.set_month(2026, 9)

    panel.prev_month()
    assert panel.month_label.text() == "2026年8月"
    assert panel.income_value_label.text() == "¥5,000.00"

    panel.next_month()
    assert panel.month_label.text() == "2026年9月"
    assert panel.income_value_label.text() == "¥3,000.00"

    # 跨年进位：1 月上一月是去年 12 月
    panel.set_month(2026, 1)
    panel.prev_month()
    assert panel.month_label.text() == "2025年12月"


def test_dashboard_empty_state(seeded_factory):
    from PySide6.QtWidgets import QApplication

    from ui.dashboard import DashboardPanel

    QApplication.instance() or QApplication([])
    panel = DashboardPanel(StatisticsService(session_factory=seeded_factory))
    panel.set_month(2026, 9)

    assert not panel.empty_label.isHidden()  # 需求 §42：友好空态
    assert panel.income_value_label.text() == "¥0.00"
    assert panel.net_value_label.text() == "¥0.00"


def test_dashboard_negative_balance(seeded_factory, transaction_service):
    """需求 §20：负余额 → 红色、进度 0、百分比 0%。"""
    from decimal import Decimal
    from datetime import date

    from PySide6.QtWidgets import QApplication

    from ui.dashboard import DashboardPanel

    QApplication.instance() or QApplication([])
    channel_id = entity_id(seeded_factory, Channel, "Salary")
    account_id = entity_id(seeded_factory, Account, "Bank")
    income_cat = entity_id(seeded_factory, Category, "Salary", INCOME)
    expense_cat = entity_id(seeded_factory, Category, "餐饮", EXPENSE)
    transaction_service.create(
        type=INCOME, amount=Decimal("5000"), date=date(2026, 9, 1),
        channel_id=channel_id, account_id=account_id, category_id=income_cat,
    )
    transaction_service.create(
        type=EXPENSE, amount=Decimal("6000"), date=date(2026, 9, 2),
        channel_id=channel_id, account_id=account_id, category_id=expense_cat,
    )

    panel = DashboardPanel(StatisticsService(session_factory=seeded_factory))
    panel.set_month(2026, 9)
    salary = next(c for c in panel.channel_cards if c.stat.channel_name == "Salary")
    assert salary.balance_label.text() == "余额 -¥1,000.00"
    assert salary.percent_label.text() == "0%"
    assert salary.progress.value() == 0


def test_dashboard_na_percent(seeded_factory):
    """需求 §20：累计收入为 0 → N/A + 进度 0。"""
    from PySide6.QtWidgets import QApplication

    from ui.dashboard import DashboardPanel

    QApplication.instance() or QApplication([])
    panel = DashboardPanel(StatisticsService(session_factory=seeded_factory))
    panel.set_month(2026, 9)
    bonus = next(c for c in panel.channel_cards if c.stat.channel_name == "Bonus")
    assert bonus.percent_label.text() == "N/A"
    assert bonus.progress.value() == 0


def test_dashboard_percent_text_formats():
    from decimal import Decimal

    from ui.dashboard import _format_percent

    assert _format_percent(Decimal("81.25")) == "81.25%"
    assert _format_percent(Decimal("80.00")) == "80%"
    assert _format_percent(Decimal("0")) == "0%"
    assert _format_percent(None) == "N/A"


# ---------- 搜索与快捷键冒烟 ----------


def test_history_panel_search_filters(seeded_factory):
    from datetime import date
    from decimal import Decimal

    from PySide6.QtWidgets import QApplication

    from ui.history_panel import HistoryPanel

    QApplication.instance() or QApplication([])
    catalog, tx_service = _make_panel_services(seeded_factory)
    channel_id = next(c.id for c in catalog.list_active_channels() if c.name == "Salary")
    account_id = next(a.id for a in catalog.list_active_accounts() if a.name == "Bank")
    tx_service.create(
        type="expense", amount=Decimal("52.00"), date=date(2026, 9, 18),
        channel_id=channel_id, account_id=account_id, note="午饭",
    )
    tx_service.create(
        type="expense", amount=Decimal("1800.00"), date=date(2026, 9, 1),
        channel_id=channel_id, account_id=account_id, note="房租",
    )

    panel = HistoryPanel(catalog, tx_service)
    panel.refresh()
    assert panel.table.rowCount() == 2

    panel.search_edit.setText("午饭")  # textChanged 实时过滤
    assert panel.table.rowCount() == 1
    assert panel.table.item(0, 6).text() == "午饭"
    assert panel.count_label.text() == "找到 1 条"

    panel.search_edit.clear()
    assert panel.table.rowCount() == 2
    assert panel.count_label.text() == "共 2 条"


def test_history_panel_sort_and_filter_state(seeded_factory):
    from datetime import date
    from decimal import Decimal

    from PySide6.QtWidgets import QApplication

    from ui.history_panel import HistoryPanel

    QApplication.instance() or QApplication([])
    catalog, tx_service = _make_panel_services(seeded_factory)
    channel_id = next(c.id for c in catalog.list_active_channels() if c.name == "Salary")
    account_id = next(a.id for a in catalog.list_active_accounts() if a.name == "Bank")
    tx_service.create(
        type="income", amount=Decimal("100.00"), date=date(2026, 9, 1),
        channel_id=channel_id, account_id=account_id, note="入",
    )
    tx_service.create(
        type="expense", amount=Decimal("50.00"), date=date(2026, 9, 2),
        channel_id=channel_id, account_id=account_id, note="出",
    )

    panel = HistoryPanel(catalog, tx_service)
    # 设置排序与筛选状态（弹窗交互在 test_dialog_flows 覆盖）
    panel._sort = [("type", "asc"), ("amount", "desc")]
    panel._filters = {"type": "expense"}
    panel._update_sort_button()
    panel._update_filter_button()
    panel.refresh()

    assert panel.sort_button.text() == "排序 · 自定义"
    assert panel.filter_button.text() == "筛选 (1)"
    assert panel.table.rowCount() == 1
    assert panel.table.item(0, 6).text() == "出"
    assert panel.count_label.text() == "找到 1 条"


def test_theme_watcher_syncs_system_change(seeded_factory, monkeypatch):
    """用户反馈：运行中切换系统明暗，跟随系统模式下应用同步更新。"""
    from PySide6.QtWidgets import QApplication

    from ui import theme
    from ui.theme import ThemeManager

    QApplication.instance() or QApplication([])
    window = _make_window(seeded_factory)  # 默认 system 模式
    app = QApplication.instance()
    ThemeManager.apply(app, "light")

    monkeypatch.setattr(theme, "is_system_dark", lambda: True)
    window._sync_system_theme()
    assert theme.current_theme() == "dark"

    monkeypatch.setattr(theme, "is_system_dark", lambda: False)
    window._sync_system_theme()
    assert theme.current_theme() == "light"
    window.close()


def test_theme_watcher_ignores_explicit_mode(seeded_factory, monkeypatch):
    from PySide6.QtWidgets import QApplication

    from ui import theme
    from ui.theme import ThemeManager

    QApplication.instance() or QApplication([])
    ThemeManager(session_factory=seeded_factory).set_mode("dark")
    window = _make_window(seeded_factory)
    ThemeManager.apply(QApplication.instance(), "dark")

    monkeypatch.setattr(theme, "is_system_dark", lambda: False)
    window._sync_system_theme()
    assert theme.current_theme() == "dark"  # 显式模式不跟随系统
    window.close()


def test_history_panel_search_by_amount(seeded_factory):
    from datetime import date
    from decimal import Decimal

    from PySide6.QtWidgets import QApplication

    from ui.history_panel import HistoryPanel

    QApplication.instance() or QApplication([])
    catalog, tx_service = _make_panel_services(seeded_factory)
    channel_id = next(c.id for c in catalog.list_active_channels() if c.name == "Salary")
    account_id = next(a.id for a in catalog.list_active_accounts() if a.name == "Bank")
    tx_service.create(
        type="expense", amount=Decimal("52.00"), date=date(2026, 9, 18),
        channel_id=channel_id, account_id=account_id, note="A",
    )
    tx_service.create(
        type="expense", amount=Decimal("53.00"), date=date(2026, 9, 18),
        channel_id=channel_id, account_id=account_id, note="B",
    )

    panel = HistoryPanel(catalog, tx_service)
    panel.search_edit.setText("52")
    assert panel.table.rowCount() == 1
    assert panel.table.item(0, 6).text() == "A"


def _make_window(seeded_factory):
    from PySide6.QtWidgets import QApplication

    from ui.main_window import MainWindow
    from ui.theme import ThemeManager

    QApplication.instance() or QApplication([])
    catalog, tx_service = _make_panel_services(seeded_factory)
    statistics = StatisticsService(session_factory=seeded_factory)
    import_svc = ImportService(session_factory=seeded_factory)
    export_svc = ExportService(session_factory=seeded_factory)
    backup_svc = BackupService(session_factory=seeded_factory)
    theme_mgr = ThemeManager(session_factory=seeded_factory)
    window = MainWindow(
        catalog, tx_service, statistics, import_svc, export_svc, backup_svc, theme_mgr
    )
    window.show()
    QApplication.processEvents()
    return window


def test_ctrl_f_focuses_search(seeded_factory):
    window = _make_window(seeded_factory)
    window.history_panel.focus_search()  # Ctrl+F 的处理器
    assert window.history_panel.search_edit.hasFocus()
    window.close()


def test_esc_shortcut_clears_search(seeded_factory):
    window = _make_window(seeded_factory)
    window.history_panel.search_edit.setText("午饭")
    assert window.history_panel.search_edit.text() == "午饭"

    window._on_esc_shortcut()
    assert window.history_panel.search_edit.text() == ""
    window.close()


def test_esc_shortcut_clears_bookkeeping_input(seeded_factory):
    window = _make_window(seeded_factory)
    form = window.bookkeeping_panel.form
    form.amount_edit.setText("99")
    form.amount_edit.setFocus()

    window._on_esc_shortcut()
    assert form.amount_edit.text() == ""
    window.close()


def test_delete_shortcut_guarded_outside_table(seeded_factory, monkeypatch):
    """焦点在输入框时 Delete 不触发删除（防止打字误删）。"""
    window = _make_window(seeded_factory)
    calls = []
    monkeypatch.setattr(
        window.history_panel, "delete_selected", lambda: calls.append(1)
    )

    window.bookkeeping_panel.form.amount_edit.setFocus()
    window._on_delete_shortcut()
    assert calls == []

    window.history_panel.table.setFocus()
    window._on_delete_shortcut()
    assert calls == [1]
    window.close()


# ---------- 数据管理冒烟 ----------


def test_data_manage_dialog_export_flow(seeded_factory, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

    from ui.dialogs.data_manage_dialog import DataManageDialog

    QApplication.instance() or QApplication([])
    export_svc = ExportService(session_factory=seeded_factory)
    import_svc = ImportService(session_factory=seeded_factory)

    infos = []
    monkeypatch.setattr(
        QMessageBox, "information", lambda *args, **kwargs: infos.append(args)
    )
    target = tmp_path / "out.json"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(target), ""))
    )

    dialog = DataManageDialog(import_svc, export_svc)
    assert dialog.export_json_button is not None
    assert dialog.import_csv_button is not None

    dialog._on_export_json()
    assert target.exists()
    assert infos


def test_data_manage_dialog_import_error_flow(seeded_factory, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

    from ui.dialogs.data_manage_dialog import DataManageDialog

    QApplication.instance() or QApplication([])
    export_svc = ExportService(session_factory=seeded_factory)
    import_svc = ImportService(session_factory=seeded_factory)

    warnings = []
    monkeypatch.setattr(
        QMessageBox, "warning", lambda *args, **kwargs: warnings.append(args)
    )
    bad_file = tmp_path / "bad.csv"
    bad_file.write_text("日期,金额\n2026-09-18,10\n", encoding="utf-8-sig")
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(bad_file), ""))
    )

    dialog = DataManageDialog(import_svc, export_svc)
    dialog._on_import_csv()
    assert warnings  # 表头错误 → 警告弹窗


# ---------- 设置弹窗冒烟 ----------


def test_settings_dialog_save_retention(seeded_factory, tmp_path):
    from PySide6.QtWidgets import QApplication

    from ui.dialogs.settings_dialog import SettingsDialog
    from ui.theme import ThemeManager

    QApplication.instance() or QApplication([])
    service = BackupService(
        session_factory=seeded_factory,
        db_path=tmp_path / "test.db",
        backup_dir=tmp_path / "backups",
    )
    theme_manager = ThemeManager(session_factory=seeded_factory)
    dialog = SettingsDialog(service, theme_manager)
    assert dialog.retention_spin.value() == 30  # 默认（需求 §34）
    assert dialog.theme_combo.currentData() == "system"  # 默认跟随系统

    dialog.retention_spin.setValue(60)
    dialog.theme_combo.setCurrentIndex(dialog.theme_combo.findData("dark"))
    dialog._on_save()
    assert service.get_retention_days() == 60
    assert ThemeManager(session_factory=seeded_factory).get_mode() == "dark"


# ---------- 历史记录翻页（用户反馈）----------


def test_history_panel_pagination(seeded_factory):
    from datetime import date
    from decimal import Decimal

    from PySide6.QtWidgets import QApplication

    from ui.history_panel import HistoryPanel

    QApplication.instance() or QApplication([])
    catalog, tx_service = _make_panel_services(seeded_factory)
    channel_id = next(c.id for c in catalog.list_active_channels() if c.name == "Salary")
    account_id = next(a.id for a in catalog.list_active_accounts() if a.name == "Bank")
    for i in range(25):
        tx_service.create(
            type="expense", amount=Decimal(f"{i + 1}.00"), date=date(2026, 9, 18),
            channel_id=channel_id, account_id=account_id, note=f"n{i}",
        )

    panel = HistoryPanel(catalog, tx_service)
    panel.refresh()

    # 默认每页 50：单页全量
    assert panel.table.rowCount() == 25
    assert panel.page_label.text() == "第 1 / 1 页"
    assert not panel.prev_button.isEnabled()
    assert not panel.next_button.isEnabled()

    # 每页 10：3 页
    panel.page_size_combo.setCurrentIndex(0)
    assert panel.table.rowCount() == 10
    assert panel.page_label.text() == "第 1 / 3 页"
    assert not panel.prev_button.isEnabled()
    assert panel.next_button.isEnabled()

    panel._next_page()
    assert panel.table.rowCount() == 10
    assert panel.page_label.text() == "第 2 / 3 页"
    assert panel.prev_button.isEnabled()

    panel._next_page()
    assert panel.table.rowCount() == 5
    assert panel.page_label.text() == "第 3 / 3 页"
    assert not panel.next_button.isEnabled()

    panel._prev_page()
    assert panel.page_label.text() == "第 2 / 3 页"
    assert panel.count_label.text() == "共 25 条"
