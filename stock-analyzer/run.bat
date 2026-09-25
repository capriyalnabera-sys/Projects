@echo off
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8

if "%~1"=="" (
    echo.
    echo Usage:
    echo   run.bat TICKER [TICKER2 ...]              ^(NSE symbols, no .NS suffix^)
    echo.
    echo Examples:
    echo   run.bat RELIANCE TCS HFCL
    echo   run.bat BORORENEW UGROCAP
    echo.
    echo Flags:
    echo   --no-pdfs          skip Telegram PDF download/parse ^(faster^)
    echo   --telegram-days N  scan last N days of Telegram ^(default 7^)
    echo.
    pause
    exit /b 1
)

.venv\Scripts\python.exe -m src.main analyze %* --with-telegram
echo.
pause
