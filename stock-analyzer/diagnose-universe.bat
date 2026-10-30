@echo off
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
if not exist ".venv\Scripts\python.exe" (
    echo Run run-web.bat once first - it sets up the Python environment.
    pause
    exit /b 1
)
echo Checking why listed stocks are missing - takes about a minute...
echo.
.venv\Scripts\python.exe scripts\diagnose_universe.py
echo.
pause
