@echo off
cd /d "%~dp0"
if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" -m unittest discover -s tests -v
) else (
    python -m unittest discover -s tests -v
)
pause
