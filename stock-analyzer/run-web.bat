@echo off
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8

echo.
echo Stock Analyzer web UI starting at http://127.0.0.1:5000/
echo Press Ctrl+C to stop the server.
echo.

start "" "http://127.0.0.1:5000/"
.venv\Scripts\python.exe -m src.web
