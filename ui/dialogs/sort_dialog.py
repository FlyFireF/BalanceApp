"""历史记录多级排序弹窗（最多 3 级，层级排序）。"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

_FIELD_OPTIONS = [
    ("date", "日期"),
    ("type", "类型"),
    ("amount", "金额"),
    ("channel", "渠道"),
    ("account", "账户"),
    ("category", "分类"),
]

_DEFAULT_SORT = [("date", "desc")]


class SortDialog(QDialog):
    """多级排序编辑：3 行「字段 + 方向」，空字段行忽略。"""

    def __init__(self, current: list | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("排序")
        self.setMinimumWidth(380)

        self._rows: list[tuple[QComboBox, QComboBox]] = []
        rows_layout = QVBoxLayout()
        for level in range(3):
            field_combo = QComboBox()
            field_combo.addItem("不使用", None)
            for value, label in _FIELD_OPTIONS:
                field_combo.addItem(label, value)
            direction_combo = QComboBox()
            direction_combo.addItem("升序", "asc")
            direction_combo.addItem("降序", "desc")
            row = QHBoxLayout()
            row.addWidget(QLabel(f"第 {level + 1} 排序"))
            row.addWidget(field_combo, 1)
            row.addWidget(direction_combo)
            rows_layout.addLayout(row)
            self._rows.append((field_combo, direction_combo))

        hint = QLabel(
            "层级排序：先按第 1 排序，相同再按第 2、第 3。\n"
            "类型升序 = 收入在前、支出在后；金额降序 = 从高到低。\n"
            "全部为空时默认按日期降序。"
        )
        hint.setObjectName("dialogInfo")

        self.apply_button = QPushButton("应用")
        self.default_button = QPushButton("恢复默认")
        self.cancel_button = QPushButton("取消")
        self.apply_button.clicked.connect(self.accept)
        self.default_button.clicked.connect(self._on_default)
        self.cancel_button.clicked.connect(self.reject)
        button_row = QHBoxLayout()
        button_row.addStretch(1)
        button_row.addWidget(self.default_button)
        button_row.addWidget(self.cancel_button)
        button_row.addWidget(self.apply_button)

        layout = QVBoxLayout(self)
        layout.addLayout(rows_layout)
        layout.addWidget(hint)
        layout.addLayout(button_row)

        self._restore(current or _DEFAULT_SORT)

    def sort(self) -> list[tuple[str, str]]:
        """当前排序设置（空则默认日期降序）。"""
        result = []
        for field_combo, direction_combo in self._rows:
            field = field_combo.currentData()
            if field:
                result.append((field, direction_combo.currentData()))
        return result or list(_DEFAULT_SORT)

    def _on_default(self) -> None:
        self._restore(_DEFAULT_SORT)
        self.accept()

    def _restore(self, sort: list[tuple[str, str]]) -> None:
        """回填排序设置。"""
        for (field_combo, direction_combo), item in zip(self._rows, sort):
            field_index = field_combo.findData(item[0])
            field_combo.setCurrentIndex(max(0, field_index))
            direction_index = direction_combo.findData(item[1])
            direction_combo.setCurrentIndex(max(0, direction_index))
