"""主题管理（用户反馈：系统深色模式下出现「白底白字」）。

三种模式：浅色（light）/ 深色（dark）/ 跟随系统（system，默认），
存于 Setting 表 key=theme，可在「设置」中修改并立即生效。

生效机制：
- QStyleHints.setColorScheme 控制原生控件（输入框/表格/下拉/按钮/弹窗）的明暗；
- QPalette 兜底（保证非 windows11 风格下也能正确着色）；
- QSS 由同一模板 + 两套配色生成，控制卡片/标签/表格选中色/进度条/滚动条。

「跟随系统」通过注册表读取 Windows 个性化设置（AppsUseLightTheme）。
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import sessionmaker

from database import database
from database.models import Setting
from services.exceptions import ValidationError

logger = logging.getLogger(__name__)

THEME_KEY = "theme"
THEME_LIGHT = "light"
THEME_DARK = "dark"
THEME_SYSTEM = "system"
THEME_VALUES = (THEME_LIGHT, THEME_DARK, THEME_SYSTEM)
DEFAULT_THEME = THEME_SYSTEM

# 当前已生效的主题（apply 时更新；未应用时默认浅色）
_current_theme = THEME_LIGHT


_COLORS = {
    THEME_LIGHT: {
        "window_bg": "#f5f6fa",
        "card_bg": "#ffffff",
        "border": "#e5e7eb",
        "text_primary": "#111827",
        "text_secondary": "#6b7280",
        "text_muted": "#9ca3af",
        "stat_bg": "#f9fafb",
        "green": "#16a34a",
        "red": "#dc2626",
        "table_alt": "#fafbfd",
        "table_grid": "#f3f4f6",
        "selection_bg": "#dbeafe",
        "selection_active_bg": "#bfdbfe",
        "progress_track": "#f3f4f6",
        "progress_border": "#e5e7eb",
        "scroll_handle": "#c9d3e0",
        "scroll_handle_hover": "#9fb1c7",
    },
    THEME_DARK: {
        "window_bg": "#1f1f1f",
        "card_bg": "#2b2b2b",
        "border": "#3d3d3d",
        "text_primary": "#e8e8e8",
        "text_secondary": "#a8a8a8",
        "text_muted": "#8a8a8a",
        "stat_bg": "#303030",
        "green": "#4ade80",
        "red": "#f87171",
        "table_alt": "#303030",
        "table_grid": "#3a3a3a",
        "selection_bg": "#3b5f8f",
        "selection_active_bg": "#4a7ab5",
        "progress_track": "#3d3d3d",
        "progress_border": "#4a4a4a",
        "scroll_handle": "#5a5a5a",
        "scroll_handle_hover": "#7a7a7a",
    },
}

# 同一模板、两套配色（双大括号为 format 转义）
_TEMPLATE = """
QMainWindow {{ background: {window_bg}; }}

/* 卡片与侧边栏 */
QFrame#card {{
    background: {card_bg};
    border: 1px solid {border};
    border-radius: 8px;
}}
QFrame#sidebar {{ background: {card_bg}; border: none; border-right: 1px solid {border}; }}
QLabel {{ background: transparent; }}
QLabel#appTitle {{ font-size: 15px; font-weight: 700; color: {text_primary}; padding: 4px 6px; }}
QLabel#cardTitle {{ font-size: 16px; font-weight: 600; color: {text_primary}; }}
QLabel#statusLabel {{ color: {green}; }}
QLabel#versionLabel {{ color: {text_muted}; font-size: 11px; padding: 0 12px; }}
QLabel#dialogInfo {{ color: {text_secondary}; }}

/* Dashboard */
QLabel#monthLabel {{ font-size: 16px; font-weight: 700; color: {text_primary}; }}
QFrame#statCard {{ background: {stat_bg}; border: 1px solid {border}; border-radius: 8px; }}
QLabel#statTitle {{ color: {text_secondary}; font-size: 12px; }}
QLabel#statValue {{ font-size: 16px; font-weight: 700; color: {text_primary}; }}
QLabel#sectionTitle {{ font-size: 14px; font-weight: 600; color: {text_primary}; }}
QFrame#channelCard {{ background: {stat_bg}; border: 1px solid {border}; border-radius: 8px; }}
QLabel#channelName {{ font-weight: 600; color: {text_primary}; }}
QLabel#inactiveTag {{
    color: {text_muted};
    font-size: 11px;
    border: 1px solid {border};
    border-radius: 4px;
    padding: 0 4px;
}}
QLabel#percentLabel {{ font-weight: 700; font-size: 14px; }}
QLabel#metricLabel {{ color: {text_secondary}; font-size: 12px; }}
QLabel#balanceLabel {{ font-weight: 600; }}
QLabel#emptyLabel {{ color: {text_muted}; font-size: 13px; padding: 8px 0; }}

/* 表格（无圆角、自选选中色，不跟随系统强调色） */
QTableWidget {{
    background: {card_bg};
    border: none;
    border-radius: 0px;
    alternate-background-color: {table_alt};
    gridline-color: {table_grid};
    outline: 0;
}}
QTableWidget::item {{ padding: 4px 8px; border-radius: 0px; }}
QTableWidget::item:selected {{
    background: {selection_bg};
    color: {text_primary};
    border-radius: 0px;
}}
QTableWidget::item:selected:active {{
    background: {selection_active_bg};
    color: {text_primary};
}}

/* 进度条 */
QProgressBar {{
    border: 1px solid {progress_border};
    border-radius: 5px;
    background: {progress_track};
    height: 8px;
}}
QProgressBar::chunk {{ border-radius: 4px; }}

/* 滚动条：扁平风格（避免落入经典风格绘制） */
QScrollBar:vertical {{ background: transparent; width: 12px; margin: 2px; }}
QScrollBar::handle:vertical {{
    background: {scroll_handle};
    border-radius: 5px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: {scroll_handle_hover}; }}
QScrollBar:horizontal {{ background: transparent; height: 12px; margin: 2px; }}
QScrollBar::handle:horizontal {{
    background: {scroll_handle};
    border-radius: 5px;
    min-width: 30px;
}}
QScrollBar::handle:horizontal:hover {{ background: {scroll_handle_hover}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
"""


def is_system_dark() -> bool:
    """Windows 系统是否处于深色模式（注册表 AppsUseLightTheme；非 Windows 视为浅色）。"""
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        ) as key:
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return value == 0
    except OSError:
        return False


def build_stylesheet(theme: str) -> str:
    """按主题生成 QSS（同一模板、两套配色）。"""
    palette = _COLORS[THEME_DARK] if theme == THEME_DARK else _COLORS[THEME_LIGHT]
    return _TEMPLATE.format(**palette)


def current_theme() -> str:
    """当前已生效的主题（默认浅色）。"""
    return _current_theme


def color(name: str) -> str:
    """当前主题下的具名颜色（如 green / red / text_primary）。"""
    return _COLORS[current_theme()][name]


class ThemeManager:
    """主题模式读写与生效。"""

    def __init__(self, session_factory: sessionmaker | None = None) -> None:
        self._session_factory = session_factory or database.get_session_factory()

    def get_mode(self) -> str:
        """当前模式：light / dark / system；缺失或非法时回退 system。"""
        with database.session_scope(self._session_factory) as session:
            setting = session.get(Setting, THEME_KEY)
            mode = setting.value if setting else DEFAULT_THEME
        return mode if mode in THEME_VALUES else DEFAULT_THEME

    def set_mode(self, mode: str) -> None:
        """修改主题模式（light / dark / system）。"""
        if mode not in THEME_VALUES:
            raise ValidationError("主题模式无效")
        with database.session_scope(self._session_factory) as session:
            setting = session.get(Setting, THEME_KEY)
            if setting is None:
                session.add(Setting(key=THEME_KEY, value=mode))
            else:
                setting.value = mode
        logger.info("主题模式修改为 %s", mode)

    def effective_theme(self, mode: str | None = None) -> str:
        """把模式解析为实际主题：system → 按系统明暗。"""
        mode = mode or self.get_mode()
        if mode == THEME_SYSTEM:
            return THEME_DARK if is_system_dark() else THEME_LIGHT
        return mode

    @staticmethod
    def apply(app, theme: str) -> None:
        """把主题应用到应用：原生控件 ColorScheme + 调色板 + QSS。"""
        global _current_theme
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QColor, QPalette

        theme = THEME_DARK if theme == THEME_DARK else THEME_LIGHT
        if theme == THEME_DARK:
            app.styleHints().setColorScheme(Qt.ColorScheme.Dark)
        else:
            app.styleHints().setColorScheme(Qt.ColorScheme.Light)

        # 两种主题都使用显式调色板（用户反馈：风格自带的标准调色板
        # 在浅色下呈土黄色，统一改为白色 / 冷灰）
        palette = QPalette()
        colors = _COLORS[theme]
        palette.setColor(QPalette.Window, QColor(colors["window_bg"]))
        palette.setColor(QPalette.WindowText, QColor(colors["text_primary"]))
        palette.setColor(QPalette.Base, QColor("#ffffff" if theme == THEME_LIGHT else colors["card_bg"]))
        palette.setColor(QPalette.AlternateBase, QColor(colors["table_alt"]))
        palette.setColor(QPalette.Text, QColor(colors["text_primary"]))
        palette.setColor(QPalette.Button, QColor("#ffffff" if theme == THEME_LIGHT else colors["stat_bg"]))
        palette.setColor(QPalette.ButtonText, QColor(colors["text_primary"]))
        palette.setColor(QPalette.PlaceholderText, QColor(colors["text_muted"]))
        palette.setColor(QPalette.ToolTipBase, QColor("#ffffff" if theme == THEME_LIGHT else colors["card_bg"]))
        palette.setColor(QPalette.ToolTipText, QColor(colors["text_primary"]))
        app.setPalette(palette)

        _current_theme = theme
        app.setStyleSheet(build_stylesheet(theme))
