@echo off
if not exist "%~dp0.venv\Scripts\pythonw.exe" (
    echo FileNest is not set up yet. Run setup.bat first.
    pause
    exit /b 1
)
start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0FileNest.pyw" %*
