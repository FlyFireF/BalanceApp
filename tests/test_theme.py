"""测试主题管理：浅色 / 深色 / 跟随系统（用户反馈）。"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from database.models import Setting
from services.exceptions import ValidationError
from ui import theme
from ui.theme import (
    THEME_DARK,
    THEME_LIGHT,
    THEME_SYSTEM,
    ThemeManager,
    build_stylesheet,
)


def test_default_mode_is_system(seeded_factory):
    assert ThemeManager(session_factory=seeded_factory).get_mode() == THEME_SYSTEM


def test_set_and_get_mode(seeded_factory):
    manager = ThemeManager(session_factory=seeded_factory)
    manager.set_mode(THEME_DARK)
    assert manager.get_mode() == THEME_DARK
    manager.set_mode(THEME_LIGHT)
    assert manager.get_mode() == THEME_LIGHT


def test_set_mode_invalid_rejected(seeded_factory):
    manager = ThemeManager(session_factory=seeded_factory)
    with pytest.raises(ValidationError):
        manager.set_mode("blue")


def test_corrupted_mode_falls_back(seeded_factory):
    with seeded_factory() as session:
        session.get(Setting, "theme").value = "blue"
        session.commit()
    assert ThemeManager(session_factory=seeded_factory).get_mode() == THEME_SYSTEM


def test_effective_theme_follows_system(seeded_factory, monkeypatch):
    manager = ThemeManager(session_factory=seeded_factory)
    monkeypatch.setattr(theme, "is_system_dark", lambda: True)
    assert manager.effective_theme(THEME_SYSTEM) == THEME_DARK
    monkeypatch.setattr(theme, "is_system_dark", lambda: False)
    assert manager.effective_theme(THEME_SYSTEM) == THEME_LIGHT
    # 显式模式不受系统影响
    assert manager.effective_theme(THEME_DARK) == THEME_DARK
    assert manager.effective_theme(THEME_LIGHT) == THEME_LIGHT


def test_build_stylesheet_differs_and_contains_key_rules():
    light = build_stylesheet(THEME_LIGHT)
    dark = build_stylesheet(THEME_DARK)
    assert light != dark
    for sheet in (light, dark):
        assert "QFrame#card" in sheet
        assert "QTableWidget::item:selected" in sheet
        assert "QScrollBar::handle:vertical" in sheet


def test_apply_switches_stylesheet(qtbot):
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    ThemeManager.apply(app, THEME_DARK)
    assert "#2b2b2b" in app.styleSheet()
    assert theme.current_theme() == THEME_DARK
    assert theme.color("card_bg") == "#2b2b2b"

    ThemeManager.apply(app, THEME_LIGHT)
    assert "#ffffff" in app.styleSheet()
    assert theme.current_theme() == THEME_LIGHT
    assert theme.color("green") == "#16a34a"


def test_apply_light_palette_uses_white_not_standard(qtbot):
    """用户反馈：浅色模式部分控件呈土黄色——显式调色板应为白色/冷灰。"""
    from PySide6.QtGui import QPalette
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    ThemeManager.apply(app, THEME_LIGHT)
    palette = app.palette()
    assert palette.color(QPalette.Base).name() == "#ffffff"
    assert palette.color(QPalette.Button).name() == "#ffffff"
    assert palette.color(QPalette.ToolTipBase).name() == "#ffffff"
