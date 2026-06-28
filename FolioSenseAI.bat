@echo off
title FolioSenseAI
cd /d "%~dp0"

:: Check for Python
python --version >nul 2>&1
if errorlevel 1 (
    py --version >nul 2>&1
    if errorlevel 1 (
        echo.
        echo  Python is not installed or not on PATH.
        echo  Download it from https://www.python.org/downloads/
        echo  When installing, check the box "Add Python to PATH" before clicking Install.
        echo.
        pause
        exit /b 1
    )
    set PYTHON=py
) else (
    set PYTHON=python
)

:: First run: set up the virtual environment and dependencies
if not exist venv\ (
    echo  Setting up FolioSenseAI for the first time — this takes about a minute...
    echo.
    powershell -ExecutionPolicy Bypass -File scripts\setup.ps1 -NoStart
    if errorlevel 1 (
        echo.
        echo  Setup failed. See the message above for details.
        pause
        exit /b 1
    )
)

echo.
echo  Starting FolioSenseAI...
echo  Your browser will open automatically at http://localhost:8000
echo  Keep this window open while using the app.  Press Ctrl+C to stop.
echo.
venv\Scripts\python.exe run.py
pause
