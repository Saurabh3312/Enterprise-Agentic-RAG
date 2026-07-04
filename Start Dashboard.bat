@echo off
setlocal enabledelayedexpansion
title Enterprise Agentic RAG - Launcher
cd /d "%~dp0"

echo ============================================================
echo   Enterprise Agentic RAG Platform - Launcher
echo ============================================================
echo.

rem ---- 1. Find a Python interpreter ----
where py >nul 2>nul
if %errorlevel%==0 (
    set "PYLAUNCHER=py -3"
) else (
    where python >nul 2>nul
    if %errorlevel%==0 (
        set "PYLAUNCHER=python"
    ) else (
        echo [X] Python was not found on this computer.
        echo.
        echo     Install Python 3.10+ from https://www.python.org/downloads/
        echo     ^(tick "Add Python to PATH" during setup^), then double-click
        echo     this file again.
        echo.
        start https://www.python.org/downloads/
        pause
        exit /b 1
    )
)

rem ---- 2. Create the virtual environment on first run only ----
if not exist "venv\Scripts\python.exe" (
    echo [*] First-time setup detected. Creating a private Python environment...
    %PYLAUNCHER% -m venv venv
    if not exist "venv\Scripts\python.exe" (
        echo [X] Failed to create the virtual environment. Please check your Python install.
        pause
        exit /b 1
    )
)

rem ---- 3. Install dependencies on first run only ----
if not exist "venv\.setup_complete" (
    echo [*] Installing dependencies - this can take a few minutes the first time.
    echo     ^(subsequent launches skip this and start in seconds^)
    echo.
    "venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
    "venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo [X] Something went wrong installing dependencies. See the errors above.
        pause
        exit /b 1
    )
    echo done> "venv\.setup_complete"
    echo.
    echo [OK] Setup complete!
    echo.
)

rem ---- 4. Check Ollama is installed (informational only, launcher.py also checks) ----
where ollama >nul 2>nul
if not %errorlevel%==0 (
    echo [!] Ollama was not detected. The dashboard will still open, but the
    echo     AI agent needs Ollama installed to answer questions.
    echo     Get it from: https://ollama.com/download
    echo.
)

rem ---- 5. Launch the dashboard ----
"venv\Scripts\python.exe" launcher.py

echo.
echo Dashboard stopped.
pause
