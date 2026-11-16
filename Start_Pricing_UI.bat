@echo off
rem ================================================
rem  Double-click this file to open the pricing UI
rem ================================================
rem  The launcher checks that pandas, numpy and requests are importable before
rem  it starts the window, and it starts the window with pythonw.exe so no
rem  console stays behind. If the environment is broken the console window
rem  stays open with the reason instead of vanishing silently.
rem
rem  Add --check to test the environment without opening the UI.
setlocal
cd /d "%~dp0"

set "PY="
py -3 -c "import sys" >nul 2>nul
if not errorlevel 1 set "PY=py -3"
if defined PY goto :have_python
python -c "import sys" >nul 2>nul
if not errorlevel 1 set "PY=python"
if defined PY goto :have_python
python3 -c "import sys" >nul 2>nul
if not errorlevel 1 set "PY=python3"
if defined PY goto :have_python

echo [ERROR] Python was not found on this computer.
echo         Install Python 3.9 or newer from https://www.python.org/downloads/
echo         and tick "Add python.exe to PATH" during setup.
goto :fail

:have_python
%PY% -m rms_core.launcher "rms_gui.py" --gui %*
if errorlevel 1 goto :fail
exit /b 0

:fail
if not defined RMS_NO_PAUSE pause
exit /b 1
