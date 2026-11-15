@echo off
setlocal
cd /d "%~dp0"
title Ind AS 116 Lease Accounting - starting
echo.
echo  Ind AS 116 Lease Accounting
echo  ===========================
echo.

rem ---- 1. Find a working Python (py launcher first, then python)
set "PY="
py -3 -c "import sys" >nul 2>nul
if errorlevel 1 goto trypython
set "PY=py -3"
goto checkversion
:trypython
python -c "import sys" >nul 2>nul
if errorlevel 1 goto nopython
set "PY=python"

rem ---- 2. Python must be 3.10 or later and 64-bit
:checkversion
%PY% -c "import sys,struct; sys.exit(0 if sys.version_info>=(3,10) and struct.calcsize('P')==8 else 1)"
if errorlevel 1 goto badversion

rem ---- 3. Create the private environment (first run only)
set "VPY=%~dp0.venv\Scripts\python.exe"
if exist "%VPY%" goto checkdeps
echo  First run: creating the application environment...
%PY% -m venv "%~dp0.venv"
if errorlevel 1 goto venvfail

rem ---- 4. Install packages if missing (first run needs internet once)
:checkdeps
"%VPY%" -c "import PySide6.QtWidgets, pandas, openpyxl" >nul 2>nul
if not errorlevel 1 goto run
echo  Installing required packages - first run only, needs internet, takes 2-5 minutes...
"%VPY%" -m pip install --upgrade pip
"%VPY%" -m pip install -r requirements.txt
if errorlevel 1 goto pipfail
"%VPY%" -c "import PySide6.QtWidgets, pandas, openpyxl"
if errorlevel 1 goto pipfail

rem ---- 5. Start the application
:run
echo  Starting the application...
"%VPY%" main.py %*
if errorlevel 1 goto apperror
goto end

:nopython
echo  ERROR: Python was not found on this PC.
echo.
echo  1. Download Python 3.12 (64-bit) from https://www.python.org/downloads/windows/
echo  2. In the installer tick "Add python.exe to PATH", then click Install Now.
echo  3. If Windows opens the Microsoft Store when you type python, turn off
echo     Settings - Apps - Advanced app settings - App execution aliases - python.exe
echo  4. Double-click run_from_source.bat again.
goto fail

:badversion
echo  ERROR: Python 3.10 or later, 64-bit, is required. Found:
%PY% -c "import sys,platform; print('  ', sys.version, platform.architecture()[0])"
echo  Install Python 3.12 64-bit from https://www.python.org/downloads/windows/
goto fail

:venvfail
echo  ERROR: Could not create the environment in:
echo  %~dp0.venv
echo  Move this folder to a location you can write to, e.g. C:\LeaseApp, and try again.
goto fail

:pipfail
echo.
echo  ERROR: Package installation failed - see the messages above.
echo  Usual causes: no internet, or a company proxy / firewall blocking pypi.org.
echo  The incomplete environment will be removed so the next run retries cleanly.
rmdir /s /q "%~dp0.venv"
goto fail

:apperror
echo.
echo  ERROR: The application stopped with an error.
echo  Details were saved to: %LOCALAPPDATA%\IndAS116LeaseApp\startup_error.log
goto fail

:fail
echo.
echo  Please send a screenshot of this window if you need help.
pause
exit /b 1

:end
endlocal
