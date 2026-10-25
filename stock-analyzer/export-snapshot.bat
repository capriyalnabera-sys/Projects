@echo off
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
if not exist ".venv\Scripts\python.exe" (
    echo Run run-web.bat once first - it sets up the Python environment.
    pause
    exit /b 1
)
echo Exporting the website as a single HTML file (uses the latest cached data)...
.venv\Scripts\python.exe scripts\export_snapshot.py %*
echo.
pause
