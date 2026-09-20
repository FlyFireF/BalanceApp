@echo off
REM 构建 MoneyManager.exe（Phase 10 打包）
REM 前置：已安装依赖（pip install -r requirements.txt -r requirements-build.txt）
cd /d "%~dp0"
.venv\Scripts\python.exe -m PyInstaller money_manager.spec
echo.
echo 构建完成，产物: dist\MoneyManager.exe
pause
