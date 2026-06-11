@echo off
title J.A.R.V.I.S - MARK XL
cd /d "%~dp0"

REM --- Require Python on the machine ---
where python >nul 2>nul
if errorlevel 1 (
    echo.
    echo [JARVIS] Python not found.
    echo [JARVIS] Install Python 3.12 from https://www.python.org/downloads/
    echo [JARVIS] During install, TICK "Add Python to PATH", then run this again.
    echo.
    pause
    exit /b 1
)

REM --- First run: build an isolated environment next to the app ---
if not exist ".venv\Scripts\python.exe" (
    echo [JARVIS] First-time setup: creating environment, please wait...
    python -m venv .venv
    if errorlevel 1 (
        echo [JARVIS] ERROR: could not create environment. Python 3.11 or 3.12 required.
        pause
        exit /b 1
    )
    ".venv\Scripts\python.exe" -m pip install --upgrade pip "setuptools<81" --quiet
)

echo [JARVIS] Starting. The FIRST run installs packages - this can take a few minutes.
".venv\Scripts\python.exe" main.py %*
pause
