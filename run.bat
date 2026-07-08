@echo off
REM Launch ProjectBudget locally at http://localhost:8000
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python was not found on PATH. Install it from https://www.python.org/downloads/
    echo and check "Add python.exe to PATH" in the installer, then re-run this script.
    exit /b 1
)

if not exist ".venv" (
    echo Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo ERROR: Failed to create the virtual environment.
        exit /b 1
    )
)

call ".venv\Scripts\activate.bat"

REM Re-install dependencies whenever requirements.txt has changed since last install.
fc /b requirements.txt ".venv\requirements.installed" >nul 2>&1
if errorlevel 1 (
    echo Installing dependencies...
    python -m pip install --upgrade pip
    pip install -r requirements.txt
    if errorlevel 1 (
        echo ERROR: Dependency install failed. See the pip output above.
        exit /b 1
    )
    copy /y requirements.txt ".venv\requirements.installed" >nul
)

echo Starting ProjectBudget on http://localhost:8000
python -m uvicorn app.main:app --port 8000
