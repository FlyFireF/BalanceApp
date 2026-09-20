"""设置弹窗（需求 §47）：备份保留天数可编辑，数据/备份目录只读展示。"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QMessageBox,
    QSpinBox,
    QVBoxLayout,
)

from config import settings
from services.backup_service import BackupService
from services.exceptions import ValidationError
from ui.theme import THEME_DARK, THEME_LIGHT, THEME_SYSTEM, ThemeManager

logger = logging.getLogger(__name__)


class SettingsDialog(QDialog):
    """设置：备份保留天数 + 主题（浅色 / 深色 / 跟随系统）。"""

    def __init__(
        self, backup_service: BackupService, theme_manager: ThemeManager, parent=None
    ) -> None:
        super().__init__(parent)
        self._backup_service = backup_service
        self._theme_manager = theme_manager
        self.setWindowTitle("设置")
        self.setMinimumWidth(440)

        self.retention_spin = QSpinBox()
        self.retention_spin.setRange(1, 3650)
        self.retention_spin.setValue(backup_service.get_retention_days())
        self.retention_spin.setSuffix(" 天")

        # 主题（用户反馈：跟随系统为默认）
        self.theme_combo = QComboBox()
        self.theme_combo.addItem("浅色", THEME_LIGHT)
        self.theme_combo.addItem("深色", THEME_DARK)
        self.theme_combo.addItem("跟随系统（默认）", THEME_SYSTEM)
        theme_index = self.theme_combo.findData(theme_manager.get_mode())
        self.theme_combo.setCurrentIndex(max(0, theme_index))

        hint = QLabel(
            f"备份默认 {settings.DEFAULT_BACKUP_RETENTION_DAYS} 天，常用值：7 / 30 / 60 / 90 / 180，"
            "超期旧备份在每次启动时自动删除。\n"
            "主题修改保存后立即生效。"
        )
        hint.setObjectName("dialogInfo")
        hint.setWordWrap(True)

        db_path_label = QLabel(str(settings.get_db_path()))
        db_path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        db_path_label.setWordWrap(True)
        backup_path_label = QLabel(str(settings.get_backup_dir()))
        backup_path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        backup_path_label.setWordWrap(True)

        form = QFormLayout()
        form.addRow("主题", self.theme_combo)
        form.addRow("备份保留天数", self.retention_spin)
        form.addRow("数据目录", db_path_label)
        form.addRow("备份目录", backup_path_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        save_button = buttons.button(QDialogButtonBox.Save)
        save_button.setText("保存")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(hint)
        layout.addWidget(buttons)

    def _on_save(self) -> None:
        try:
            self._backup_service.set_retention_days(self.retention_spin.value())
            self._theme_manager.set_mode(self.theme_combo.currentData())
        except ValidationError as exc:
            QMessageBox.warning(self, "无法保存", str(exc))
            return
        except Exception:
            logger.exception("保存设置失败")
            QMessageBox.critical(self, "错误", "保存失败，请查看日志。")
            return
        # 主题立即生效
        app = QApplication.instance()
        if app is not None:
            ThemeManager.apply(
                app, self._theme_manager.effective_theme(self.theme_combo.currentData())
            )
        self.accept()
