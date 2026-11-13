@echo off
REM ---------------------------------------------------------------
REM  Builds the standalone Windows application (dist\IndAS116LeaseApp)
REM  Requires Python 3.10+ (64-bit) installed on this Windows PC.
REM ---------------------------------------------------------------
cd /d %~dp0
python -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m pytest -q tests || (echo TESTS FAILED - build stopped & exit /b 1)
pyinstaller --noconfirm --clean --windowed --name IndAS116LeaseApp ^
  --add-data "templates;templates" --add-data "docs;docs" ^
  --exclude-module PySide6.QtWebEngineCore --exclude-module PySide6.QtWebEngineWidgets ^
  --exclude-module PySide6.Qt3DCore --exclude-module tkinter ^
  main.py
echo.
echo Build complete: dist\IndAS116LeaseApp\IndAS116LeaseApp.exe
echo Copy the whole dist\IndAS116LeaseApp folder to any Windows PC - no Python needed there.
pause
