"""Money Manager 应用入口。

初始化日志与数据库 → 每日自动备份 → 应用主题 → 打开三栏主窗口。
完整功能说明见 README.md。
"""

from __future__ import annotations

import logging
import sys


def _install_excepthook() -> None:
    """未处理异常兜底：写入日志，避免静默崩溃（需求 §48/§49）。"""

    def handle(exc_type, exc_value, exc_tb):
        logging.getLogger("app").critical(
            "未处理异常", exc_info=(exc_type, exc_value, exc_tb)
        )
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = handle


def main() -> int:
    from config import settings
    from utils.logger import setup_logging

    settings.ensure_directories()
    setup_logging(settings.get_log_dir())
    _install_excepthook()

    logger = logging.getLogger("app")
    logger.info("Money Manager %s 启动", settings.APP_VERSION)

    # 数据库初始化：建缺失的表 + 写入默认数据 + 应用迁移（不丢数据）
    try:
        from database.database import init_db

        init_db()
    except Exception:
        logger.exception("数据库初始化失败")
        from PySide6.QtWidgets import QApplication, QMessageBox

        app = QApplication(sys.argv)
        QMessageBox.critical(None, settings.APP_NAME, "数据库初始化失败，请查看日志文件。")
        return 1

    from PySide6.QtWidgets import QApplication, QStyleFactory

    from services.backup_service import BackupService
    from services.catalog_service import CatalogService
    from services.export_service import ExportService
    from services.import_service import ImportService
    from services.statistics_service import StatisticsService
    from services.transaction_service import TransactionService
    from ui.main_window import MainWindow
    from ui.theme import ThemeManager

    app = QApplication(sys.argv)
    # Windows 原生风格（用户反馈）：输入框/表格/下拉/日历/弹窗由系统绘制，
    # 避免经典（Win98 风）样式；优先 windows11，回退 windowsvista。
    for style_name in ("windows11", "windowsvista"):
        style = QStyleFactory.create(style_name)
        if style is not None:
            app.setStyle(style)
            break
    # 字体统一在代码中设置（不经 QSS，避免触发经典风格回退）
    from PySide6.QtGui import QFont

    app.setFont(QFont("Microsoft YaHei UI", 10))
    # 主题（用户反馈：浅色 / 深色 / 跟随系统，默认跟随系统）
    theme_manager = ThemeManager()
    ThemeManager.apply(app, theme_manager.effective_theme())

    catalog_service = CatalogService()
    transaction_service = TransactionService()
    statistics_service = StatisticsService()
    import_service = ImportService()
    export_service = ExportService()
    backup_service = BackupService()

    # 每日自动备份（需求 §33）：当天已备份则不重复；失败不阻塞启动
    try:
        result = backup_service.daily_backup()
        if result is not None:
            logger.info("今日自动备份完成：%s", result.backup_file)
    except Exception:
        logger.exception("自动备份失败")

    window = MainWindow(
        catalog_service, transaction_service, statistics_service,
        import_service, export_service, backup_service, theme_manager,
    )
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
