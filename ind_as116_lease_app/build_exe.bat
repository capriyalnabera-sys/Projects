@echo off
setlocal
rem ---------------------------------------------------------------
rem  Builds the standalone Windows application: dist\IndAS116LeaseApp
rem  Needs Python 3.10+ 64-bit. Run run_from_source.bat once first.
rem ---------------------------------------------------------------
cd /d "%~dp0"
set "VPY=%~dp0.venv\Scripts\python.exe"
if exist "%VPY%" goto deps
echo Run run_from_source.bat once first to create the environment.
pause
exit /b 1
:deps
"%VPY%" -m pip install -r requirements.txt -r requirements-dev.txt
if errorlevel 1 goto fail
"%VPY%" -m pytest -q tests
if errorlevel 1 goto testfail
"%VPY%" -m PyInstaller --noconfirm --clean --windowed --name IndAS116LeaseApp --icon assets\app_icon.ico --add-data "assets;assets" --exclude-module PySide6.QtWebEngineCore --exclude-module PySide6.QtWebEngineWidgets --exclude-module tkinter main.py
if errorlevel 1 goto fail
echo.
echo Build complete: dist\IndAS116LeaseApp\IndAS116LeaseApp.exe
echo Copy the whole dist\IndAS116LeaseApp folder to any Windows PC. For an installer, compile
echo installer\IndAS116LeaseApp.iss with Inno Setup 6.
pause
exit /b 0
:testfail
echo TESTS FAILED - build stopped.
:fail
pause
exit /b 1
