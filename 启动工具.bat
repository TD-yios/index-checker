@echo off
chcp 65001 >nul
cd /d "%~dp0"

set "PYEXE="
if exist "%~dp0.venv\Scripts\python.exe" set "PYEXE=%~dp0.venv\Scripts\python.exe"

if not "%PYEXE%"=="" goto run
where python >nul 2>nul
if errorlevel 1 (
    echo 未找到 Python 运行环境，请先双击「安装依赖.bat」。
    pause
    exit /b 1
)
python app.py
if errorlevel 1 pause
exit /b 0

:run
"%PYEXE%" app.py
if errorlevel 1 pause
exit /b 0
