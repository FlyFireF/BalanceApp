# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置（Phase 10，需求 §52）。

构建：python -m PyInstaller money_manager.spec
产物：dist/MoneyManager.exe —— 单文件、双击运行、无控制台窗口。

数据说明：数据库/备份/日志位于 %LOCALAPPDATA%\\MoneyManager（config/settings.py），
与程序文件分离——升级 exe、移动 exe 都不影响用户数据（需求 Phase 10 要求）。

如需自定义图标：把 icon.ico 放在项目根目录，将下方 icon=None 改为 icon="icon.ico"。
"""

a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="MoneyManager",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # 图形应用：不显示黑色控制台（等价 pythonw 行为）
    disable_windowed_traceback=False,
    icon=None,  # 可替换为 "icon.ico"
)
