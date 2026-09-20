"""数据管理弹窗：导入 / 导出（需求 §28-§32）。

导入安全说明：任何一行有错则整体不导入；同名实体复用、重复交易跳过，
绝不覆盖或删除现有数据。
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from services.export_service import ExportService
from services.import_service import ImportService

logger = logging.getLogger(__name__)


class DataManageDialog(QDialog):
    """数据导入导出入口。导入成功后发出 imported 信号（主窗口据此刷新）。"""

    imported = Signal()

    def __init__(
        self,
        import_service: ImportService,
        export_service: ExportService,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._import_service = import_service
        self._export_service = export_service
        self.setWindowTitle("数据管理")
        self.setMinimumWidth(460)

        info = QLabel(
            "导出：把当前数据保存为文件（备份 / 迁移）。\n"
            "导入：从文件恢复数据——同名渠道/账户/分类复用现有项，重复的交易自动跳过；\n"
            "任何一行有错则整体不导入，绝不覆盖或删除现有数据。"
        )
        info.setObjectName("dialogInfo")
        info.setWordWrap(True)

        export_title = QLabel("导出")
        export_title.setObjectName("sectionTitle")
        self.export_json_button = QPushButton("导出 JSON（完整备份）")
        self.export_csv_button = QPushButton("导出 CSV（交易）")
        self.export_xlsx_button = QPushButton("导出 XLSX（Excel）")
        self.export_json_button.clicked.connect(self._on_export_json)
        self.export_csv_button.clicked.connect(self._on_export_csv)
        self.export_xlsx_button.clicked.connect(self._on_export_xlsx)
        export_row = QHBoxLayout()
        export_row.addWidget(self.export_json_button)
        export_row.addWidget(self.export_csv_button)
        export_row.addWidget(self.export_xlsx_button)
        export_row.addStretch(1)

        import_title = QLabel("导入")
        import_title.setObjectName("sectionTitle")
        self.import_json_button = QPushButton("导入 JSON")
        self.import_csv_button = QPushButton("导入 CSV")
        self.import_xlsx_button = QPushButton("导入 XLSX")
        self.import_json_button.clicked.connect(self._on_import_json)
        self.import_csv_button.clicked.connect(self._on_import_csv)
        self.import_xlsx_button.clicked.connect(self._on_import_xlsx)
        import_row = QHBoxLayout()
        import_row.addWidget(self.import_json_button)
        import_row.addWidget(self.import_csv_button)
        import_row.addWidget(self.import_xlsx_button)
        import_row.addStretch(1)

        close_button = QPushButton("关闭")
        close_button.clicked.connect(self.accept)
        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close_row.addWidget(close_button)

        layout = QVBoxLayout(self)
        layout.addWidget(info)
        layout.addSpacing(8)
        layout.addWidget(export_title)
        layout.addLayout(export_row)
        layout.addSpacing(8)
        layout.addWidget(import_title)
        layout.addLayout(import_row)
        layout.addSpacing(8)
        layout.addLayout(close_row)

    # ---------- 导出 ----------

    def _on_export_json(self) -> None:
        path = self._save_path("导出 JSON", f"money_manager_backup_{date.today():%Y%m%d}.json", "JSON 文件 (*.json)")
        if path is None:
            return
        try:
            counts = self._export_service.export_json(path)
        except Exception:
            logger.exception("导出 JSON 失败")
            QMessageBox.critical(self, "错误", "导出失败，请查看日志。")
            return
        QMessageBox.information(
            self,
            "导出成功",
            f"已导出：渠道 {counts['channels']} 个 / 账户 {counts['accounts']} 个 / "
            f"分类 {counts['categories']} 个 / 交易 {counts['transactions']} 笔\n\n{path}",
        )

    def _on_export_csv(self) -> None:
        path = self._save_path("导出 CSV", f"money_manager_transactions_{date.today():%Y%m%d}.csv", "CSV 文件 (*.csv)")
        if path is None:
            return
        try:
            counts = self._export_service.export_csv(path)
        except Exception:
            logger.exception("导出 CSV 失败")
            QMessageBox.critical(self, "错误", "导出失败，请查看日志。")
            return
        QMessageBox.information(self, "导出成功", f"已导出交易 {counts['transactions']} 笔\n\n{path}")

    def _on_export_xlsx(self) -> None:
        path = self._save_path("导出 XLSX", f"money_manager_{date.today():%Y%m%d}.xlsx", "Excel 文件 (*.xlsx)")
        if path is None:
            return
        try:
            counts = self._export_service.export_xlsx(path)
        except Exception:
            logger.exception("导出 XLSX 失败")
            QMessageBox.critical(self, "错误", "导出失败，请查看日志。")
            return
        QMessageBox.information(
            self,
            "导出成功",
            f"已导出：渠道 {counts['channels']} 个 / 账户 {counts['accounts']} 个 / "
            f"分类 {counts['categories']} 个 / 交易 {counts['transactions']} 笔\n\n{path}",
        )

    # ---------- 导入 ----------

    def _on_import_json(self) -> None:
        path = self._open_path("导入 JSON", "JSON 文件 (*.json)")
        if path is None:
            return
        try:
            result = self._import_service.import_json(path)
        except Exception:
            logger.exception("导入 JSON 失败")
            QMessageBox.critical(self, "错误", "导入失败，请查看日志。")
            return
        self._show_result(result)

    def _on_import_csv(self) -> None:
        path = self._open_path("导入 CSV", "CSV 文件 (*.csv)")
        if path is None:
            return
        try:
            result = self._import_service.import_csv(path)
        except Exception:
            logger.exception("导入 CSV 失败")
            QMessageBox.critical(self, "错误", "导入失败，请查看日志。")
            return
        self._show_result(result)

    def _on_import_xlsx(self) -> None:
        path = self._open_path("导入 XLSX", "Excel 文件 (*.xlsx)")
        if path is None:
            return
        try:
            result = self._import_service.import_xlsx(path)
        except Exception:
            logger.exception("导入 XLSX 失败")
            QMessageBox.critical(self, "错误", "导入失败，请查看日志。")
            return
        self._show_result(result)

    def _show_result(self, result) -> None:
        if result.errors:
            shown = "\n".join(result.errors[:10])
            more = f"\n… 共 {len(result.errors)} 个错误" if len(result.errors) > 10 else ""
            QMessageBox.warning(self, "导入失败（未导入任何数据）", shown + more)
            return
        message = result.summary()
        if result.warnings:
            shown_warnings = "\n".join(result.warnings[:5])
            more = (
                f"\n… 共 {len(result.warnings)} 条警告"
                if len(result.warnings) > 5
                else ""
            )
            message += f"\n\n警告（不影响导入）：\n{shown_warnings}{more}"
        QMessageBox.information(self, "导入完成", message)
        self.imported.emit()

    # ---------- 文件对话框 ----------

    def _save_path(self, title: str, filename: str, filter_text: str) -> Path | None:
        path, _ = QFileDialog.getSaveFileName(
            self, title, str(Path.home() / filename), filter_text
        )
        return Path(path) if path else None

    def _open_path(self, title: str, filter_text: str) -> Path | None:
        path, _ = QFileDialog.getOpenFileName(self, title, str(Path.home()), filter_text)
        return Path(path) if path else None
