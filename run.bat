@echo off
REM Launch ProjectBudget locally at http://localhost:8000
cd /d "%~dp0"

if not exist ".venv" (
    echo Creating virtual environment...
    python -m venv .venv
    call ".venv\Scripts\activate.bat"
    echo Installing dependencies...
    python -m pip install --upgrade pip
    pip install -r requirements.txt
) else (
    call ".venv\Scripts\activate.bat"
)

echo Starting ProjectBudget on http://localhost:8000
python -m uvicorn app.main:app --port 8000
