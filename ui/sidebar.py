"""左侧导航栏（需求 §10）：记账 / Dashboard / 渠道·账户·分类管理入口。"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout

from config import settings


class Sidebar(QFrame):
    """左侧导航。点击项发出 nav_clicked(str)，由主窗口统一处理。"""

    nav_clicked = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setFixedWidth(150)

        # 标题分两行显示（侧边栏宽度不足时保持完整可见）
        title = QLabel("Money\nManager")
        title.setObjectName("appTitle")

        # 仅「记账 / Dashboard」是可切换状态的按钮；
        # 管理类入口直接打开弹窗，不使用 on/off 状态（用户反馈）
        self.bookkeeping_button = self._nav_button("记账", checkable=True, checked=True)
        self.dashboard_button = self._nav_button("Dashboard", checkable=True, checked=True)
        self.channel_button = self._nav_button("渠道管理")
        self.account_button = self._nav_button("账户管理")
        self.category_button = self._nav_button("分类管理")
        self.data_button = self._nav_button("数据管理")
        self.settings_button = self._nav_button("设置")

        version = QLabel(f"v{settings.APP_VERSION}")
        version.setObjectName("versionLabel")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 16, 12, 12)
        layout.setSpacing(4)
        layout.addWidget(title)
        layout.addSpacing(12)
        layout.addWidget(self.bookkeeping_button)
        layout.addWidget(self.dashboard_button)
        layout.addSpacing(16)
        layout.addWidget(self.channel_button)
        layout.addWidget(self.account_button)
        layout.addWidget(self.category_button)
        layout.addWidget(self.data_button)
        layout.addWidget(self.settings_button)
        layout.addStretch(1)
        layout.addWidget(version)

        self.bookkeeping_button.clicked.connect(lambda: self.nav_clicked.emit("bookkeeping"))
        self.dashboard_button.clicked.connect(lambda: self.nav_clicked.emit("dashboard"))
        self.channel_button.clicked.connect(lambda: self.nav_clicked.emit("channels"))
        self.account_button.clicked.connect(lambda: self.nav_clicked.emit("accounts"))
        self.category_button.clicked.connect(lambda: self.nav_clicked.emit("categories"))
        self.data_button.clicked.connect(lambda: self.nav_clicked.emit("data"))
        self.settings_button.clicked.connect(lambda: self.nav_clicked.emit("settings"))

    def _nav_button(
        self, text: str, checkable: bool = False, checked: bool = False
    ) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("navButton")
        button.setCheckable(checkable)
        button.setChecked(checked)
        button.setCursor(Qt.PointingHandCursor)
        return button
