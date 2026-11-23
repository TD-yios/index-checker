@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

if not exist "%~dp0.venv\Scripts\python.exe" (
    echo Python virtual environment not found. Run 安装依赖.bat first.
    pause
    exit /b 1
)
set "PYEXE=%~dp0.venv\Scripts\python.exe"

if not exist "vendor\chrome-win64\chrome.exe" (
    echo Bundled Chrome not found. Downloading Chrome for Testing ...
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0准备内置浏览器.ps1"
    if errorlevel 1 (
        echo Bundled Chrome download failed. Check network and retry.
        pause
        exit /b 1
    )
)

if not exist "assets\app.ico" (
    echo App icon not found: assets\app.ico
    pause
    exit /b 1
)

echo Installing PyInstaller ...
"%PYEXE%" -m pip install pyinstaller

echo Building IndexChecker ...
"%PYEXE%" -m PyInstaller --noconfirm --clean --noconsole --name IndexChecker ^
    --icon "assets\app.ico" ^
    --add-data "assets\app.ico;assets" ^
    --exclude-module PIL ^
    --hidden-import core.checker ^
    --hidden-import core.report ^
    --hidden-import core.browser ^
    --hidden-import core.library ^
    --hidden-import core.proxy ^
    --hidden-import runner ^
    app.py

if errorlevel 1 (
    echo Build failed. See the log above.
    pause
    exit /b 1
)

echo Copying bundled Chrome ...
if exist "dist\IndexChecker\browser" rmdir /s /q "dist\IndexChecker\browser"
xcopy "vendor\chrome-win64" "dist\IndexChecker\browser\chrome-win64\" /E /I /Y /Q >nul
if errorlevel 1 (
    echo Failed to copy bundled Chrome.
    pause
    exit /b 1
)

echo.
echo Build complete: dist\IndexChecker\IndexChecker.exe
echo Copy the whole IndexChecker folder, not only the exe.
pause
