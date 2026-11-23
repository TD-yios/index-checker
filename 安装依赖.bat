@echo off
chcp 65001 >nul
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo 未检测到 Python，请先安装 Python 3.10+ 并勾选 Add python.exe to PATH。
    echo 下载地址：https://www.python.org/downloads/windows/
    pause
    exit /b 1
)

set "VENV=%~dp0.venv"

echo [1/4] 创建虚拟环境 .venv ...
if not exist "%VENV%\Scripts\python.exe" python -m venv "%VENV%"

echo [2/4] 升级 pip ...
"%VENV%\Scripts\python.exe" -m pip install --upgrade pip

echo [3/4] 安装依赖 ...
"%VENV%\Scripts\python.exe" -m pip install -r requirements.txt

echo [4/4] 下载浏览器内核（备用，若本机已装 Chrome 可跳过）...
set "PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright"
"%VENV%\Scripts\python.exe" -m playwright install chromium

echo.
echo 安装完成，双击「启动工具.bat」开始使用。
pause
