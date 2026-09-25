@echo off
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8

rem ---- First run: create the virtualenv automatically -----------------------
if not exist ".venv\Scripts\python.exe" (
    echo First run - creating Python environment in .venv ...
    python -m venv .venv
)
if not exist ".venv\Scripts\python.exe" (
    py -m venv .venv
)
if not exist ".venv\Scripts\python.exe" (
    echo.
    echo Could not create .venv - is Python 3.10+ installed and on PATH?
    echo Install from https://www.python.org/downloads/ and tick "Add to PATH".
    pause
    exit /b 1
)

rem ---- Install dependencies if missing --------------------------------------
.venv\Scripts\python.exe -c "import flask, yfinance, brotli" 2>nul
if errorlevel 1 (
    echo Installing dependencies - one-time, takes a few minutes...
    .venv\Scripts\python.exe -m pip install -r requirements.txt
)

rem ---- Default config on first run -------------------------------------------
if not exist "config.yaml" copy config.example.yaml config.yaml >nul

rem ---- Desktop shortcut so next launch is a double-click ---------------------
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ws = New-Object -ComObject WScript.Shell; $lnk = [Environment]::GetFolderPath('Desktop') + '\Stock Analyzer.lnk'; if (-not (Test-Path $lnk)) { $sc = $ws.CreateShortcut($lnk); $sc.TargetPath = '%~dp0run-web.bat'; $sc.WorkingDirectory = '%~dp0'; $sc.IconLocation = '%%SystemRoot%%\System32\shell32.dll,137'; $sc.Save(); Write-Host 'Created desktop shortcut: Stock Analyzer' }" 2>nul

echo.
echo Stock Analyzer 2.0 starting at http://127.0.0.1:5000/
echo F^&O dashboard:              http://127.0.0.1:5000/fno
echo Press Ctrl+C to stop the server.
echo.

start "" "http://127.0.0.1:5000/fno"
.venv\Scripts\python.exe -m src.web
pause
