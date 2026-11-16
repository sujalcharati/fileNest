@echo off
setlocal
cd /d "%~dp0"
echo.
echo  FileNest setup
echo  ==============

rem Prefer the Python launcher (py), fall back to python on PATH.
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY (
    echo  Python was not found. Install Python 3.12+ from https://www.python.org/downloads/
    echo  and tick "Add python.exe to PATH" during installation.
    pause
    exit /b 1
)

%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)"
if errorlevel 1 (
    echo  FileNest needs Python 3.12 or newer. You have:
    %PY% --version
    pause
    exit /b 1
)

rem Some files inside the UI library have very deep paths; Windows' 260-character
rem limit breaks the install when this folder's own path is too long.
%PY% -c "import os, sys; sys.exit(1 if len(os.getcwd()) > 90 else 0)"
if errorlevel 1 (
    echo.
    echo  This folder's path is too long for Windows to install FileNest here:
    echo    %CD%
    echo  Move the FileNest folder somewhere shorter, e.g. C:\Users\%USERNAME%\FileNest
    echo  and run setup.bat again. Or enable "Win32 long paths" in Windows - see README.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo  Creating a private Python environment in .venv ...
    %PY% -m venv .venv || goto :fail
)

echo  Installing dependencies ...
".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip || goto :fail
".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt || goto :fail

echo  Setup complete.
if /i "%~1"=="--no-launch" exit /b 0
echo  Starting FileNest - look for its icon in the system tray, then press Alt+Space.
start "" ".venv\Scripts\pythonw.exe" "%~dp0FileNest.pyw"
exit /b 0

:fail
echo.
echo  Setup failed - see the messages above.
pause
exit /b 1
