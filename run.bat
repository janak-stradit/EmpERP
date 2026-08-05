@echo off
REM Run the Stradit Workforce ERP (FastAPI) app locally.
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [run.bat] .venv not found. Create it first, e.g.:
    echo     python -m venv .venv
    echo     .venv\Scripts\pip install -r requirements.txt
    exit /b 1
)

if not exist ".env" (
    echo [run.bat] .env not found. Copying .env.example to .env - update it with real values before using in production.
    copy /y ".env.example" ".env" >nul
)

echo [run.bat] Starting Stradit Workforce ERP on http://127.0.0.1:8000 ...
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

endlocal
