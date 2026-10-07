@echo off
chcp 65001 >nul
title 锐同面板 Ruitong Panel

:: ---------- 自动提权（UAC） ----------
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [*] 正在请求管理员权限...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

cd /d "%~dp0backend"
where python >nul 2>nul || (echo [错误] 未检测到 Python，请先安装 Python 3.8+ && pause && exit /b 1)
if not exist ".deps\fastapi" (
    echo [*] 首次运行：正在安装依赖...
    python -m pip install -r requirements.txt --target .deps
    if errorlevel 1 (echo [错误] 依赖安装失败，请检查网络后重试 && pause && exit /b 1)
)
echo [*] 锐同面板启动中: http://127.0.0.1:8000
python run.py
pause
