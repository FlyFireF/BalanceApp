"""数据管理弹窗：导入 / 导出（需求 §28-§32）。

导入安全说明：任何一行有错则整体不导入；同名实体复用、重复交易跳过，
绝不覆盖或删除现有数据。
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from PySide6.QtCore import QDate, Signal
from PySide6.QtWidgets import (
    QDateEdit,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
)

from services.export_service import ExportService, month_export_range
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
        self.setMinimumWidth(520)

        info = QLabel(
            "导出：把当前数据保存为文件（备份 / 迁移）。\n"
            "导入：从文件恢复数据——同名渠道/账户/分类复用现有项，重复的交易自动跳过；\n"
            "任何一行有错则整体不导入，绝不覆盖或删除现有数据。"
        )
        info.setObjectName("dialogInfo")
        info.setWordWrap(True)

        export_title = QLabel("导出")
        export_title.setObjectName("sectionTitle")

        # 导出范围（仅作用于 CSV / XLSX；JSON 始终全量）
        export_range_hint = QLabel("导出范围（CSV / XLSX；JSON 始终导出完整数据）：")
        export_range_hint.setObjectName("dialogInfo")

        self.export_all_radio = QRadioButton("全部数据")
        self.export_all_radio.setChecked(True)

        self.export_month_radio = QRadioButton("指定月份")
        self.export_month_edit = QDateEdit()
        self.export_month_edit.setCalendarPopup(True)
        self.export_month_edit.setDisplayFormat("yyyy-MM")
        self.export_month_edit.setDate(QDate.currentDate())
        self.export_month_edit.setMinimumDate(QDate(1900, 1, 1))
        self.export_month_edit.setMaximumDate(QDate.currentDate())
        month_row = QHBoxLayout()
        month_row.addWidget(self.export_month_radio)
        month_row.addWidget(self.export_month_edit)
        month_row.addWidget(QLabel("（本月导出 1 日 ~ 今天）"))
        month_row.addStretch(1)

        self.export_range_radio = QRadioButton("自定义范围")
        today = QDate.currentDate()
        self.export_range_start_edit = self._make_date_edit(
            QDate(today.year(), today.month(), 1)
        )
        self.export_range_end_edit = self._make_date_edit(today)
        range_row = QHBoxLayout()
        range_row.addWidget(self.export_range_radio)
        range_row.addWidget(self.export_range_start_edit)
        range_row.addWidget(QLabel("至"))
        range_row.addWidget(self.export_range_end_edit)
        range_row.addWidget(QLabel("（含首尾，可同一天）"))
        range_row.addStretch(1)

        for radio in (
            self.export_all_radio,
            self.export_month_radio,
            self.export_range_radio,
        ):
            radio.toggled.connect(self._sync_export_controls)
        self._sync_export_controls()

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
        layout.addWidget(export_range_hint)
        layout.addWidget(self.export_all_radio)
        layout.addLayout(month_row)
        layout.addLayout(range_row)
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
        try:
            date_from, date_to = self._selected_export_range()
        except ValueError as exc:
            QMessageBox.warning(self, "无法导出", str(exc))
            return
        filename = self._export_filename(
            "money_manager_transactions", "csv", date_from, date_to
        )
        path = self._save_path("导出 CSV", filename, "CSV 文件 (*.csv)")
        if path is None:
            return
        try:
            counts = self._export_service.export_csv(
                path, date_from=date_from, date_to=date_to
            )
        except Exception:
            logger.exception("导出 CSV 失败")
            QMessageBox.critical(self, "错误", "导出失败，请查看日志。")
            return
        QMessageBox.information(
            self,
            "导出成功",
            f"已导出交易 {counts['transactions']} 笔{self._range_suffix(date_from, date_to)}"
            f"\n\n{path}",
        )

    def _on_export_xlsx(self) -> None:
        try:
            date_from, date_to = self._selected_export_range()
        except ValueError as exc:
            QMessageBox.warning(self, "无法导出", str(exc))
            return
        filename = self._export_filename("money_manager", "xlsx", date_from, date_to)
        path = self._save_path("导出 XLSX", filename, "Excel 文件 (*.xlsx)")
        if path is None:
            return
        try:
            counts = self._export_service.export_xlsx(
                path, date_from=date_from, date_to=date_to
            )
        except Exception:
            logger.exception("导出 XLSX 失败")
            QMessageBox.critical(self, "错误", "导出失败，请查看日志。")
            return
        QMessageBox.information(
            self,
            "导出成功",
            f"已导出：渠道 {counts['channels']} 个 / 账户 {counts['accounts']} 个 / "
            f"分类 {counts['categories']} 个 / 交易 {counts['transactions']} 笔"
            f"{self._range_suffix(date_from, date_to)}\n\n{path}",
        )

    # ---------- 导出范围 ----------

    @staticmethod
    def _make_date_edit(value: QDate) -> QDateEdit:
        edit = QDateEdit()
        edit.setCalendarPopup(True)
        edit.setDisplayFormat("yyyy-MM-dd")
        edit.setDate(value)
        edit.setMinimumDate(QDate(1900, 1, 1))
        edit.setMaximumDate(QDate(3000, 12, 31))
        return edit

    def _sync_export_controls(self) -> None:
        """仅在对应选项被选中时启用日期控件。"""
        self.export_month_edit.setEnabled(self.export_month_radio.isChecked())
        custom = self.export_range_radio.isChecked()
        self.export_range_start_edit.setEnabled(custom)
        self.export_range_end_edit.setEnabled(custom)

    def _selected_export_range(self) -> tuple[date | None, date | None]:
        """当前导出范围（含首尾）；「全部数据」返回 (None, None)。

        Raises:
            ValueError: 自定义范围的开始日期晚于结束日期。
        """
        if self.export_month_radio.isChecked():
            month = self.export_month_edit.date()
            return month_export_range(month.year(), month.month())
        if self.export_range_radio.isChecked():
            start = self.export_range_start_edit.date()
            end = self.export_range_end_edit.date()
            date_from = date(start.year(), start.month(), start.day())
            date_to = date(end.year(), end.month(), end.day())
            if date_from > date_to:
                raise ValueError("开始日期不能晚于结束日期")
            return date_from, date_to
        return None, None

    @staticmethod
    def _export_filename(
        base: str, suffix: str, date_from: date | None, date_to: date | None
    ) -> str:
        """默认文件名：全量导出用当天日期，范围导出附加起止日期。"""
        if date_from is None or date_to is None:
            return f"{base}_{date.today():%Y%m%d}.{suffix}"
        return f"{base}_{date_from:%Y%m%d}-{date_to:%Y%m%d}.{suffix}"

    @staticmethod
    def _range_suffix(date_from: date | None, date_to: date | None) -> str:
        if date_from is None or date_to is None:
            return ""
        return f"\n导出范围：{date_from:%Y-%m-%d} ~ {date_to:%Y-%m-%d}（含首尾）"

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
