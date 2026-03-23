@echo off
setlocal
chcp 65001 >nul

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Python virtual environment not found: .venv\Scripts\python.exe
  echo Please create the virtual environment and install dependencies first.
  pause
  exit /b 1
)

if not exist ".runtime_tmp" mkdir ".runtime_tmp"

if not exist ".env" (
  if exist ".env.example" (
    copy /Y ".env.example" ".env" >nul
    echo [INFO] Created .env from .env.example
  ) else (
    echo [WARN] .env was not found and no .env.example is available.
  )
)

start "audit-validator" cmd /k "cd /d %~dp0 && .venv\Scripts\python.exe -m streamlit run app_demo.py --server.headless=true --server.port=8501 --browser.gatherUsageStats=false"

echo Validator is starting in a new window.
echo Open http://localhost:8501 after a few seconds.
timeout /t 3 >nul

endlocal
