@echo off
rem ================================================
rem  Double-click: run one pricing cycle immediately
rem ================================================
rem  The actual start is done by rms_core\launcher.py, which probes each
rem  installed interpreter and uses the first one that really has pandas,
rem  numpy and requests. A plain "where python" only proves that a name
rem  exists, and on this kind of machine it often points at an interpreter
rem  without those packages.
rem
rem  Add --check to diagnose the environment without running pricing.
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
%PY% -m rms_core.launcher "hotel rms.py" %*
if errorlevel 1 goto :fail
rem Keep the window open so a double-click user can read the result. Set
rem RMS_NO_PAUSE=1 to suppress it when running unattended.
if not defined RMS_NO_PAUSE pause
exit /b 0

:fail
if not defined RMS_NO_PAUSE pause
exit /b 1
