@echo off
setlocal
chcp 65001 >nul
title Audit Validator Launcher
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Python virtual environment not found: .venv\Scripts\python.exe
  echo Please create the virtual environment and install dependencies first.
  pause
  exit /b 1
)

if not exist ".env" (
  if exist ".env.example" (
    copy /Y ".env.example" ".env" >nul
    echo [INFO] Created .env from .env.example
  ) else (
    echo [ERROR] Missing both .env and .env.example
    pause
    exit /b 1
  )
)

if not exist ".runtime_tmp" mkdir ".runtime_tmp"

echo Starting validator UI...
echo Browser URL: http://localhost:8501
echo Keep this window open while the service is running.
echo.

start "" cmd /c "timeout /t 3 >nul && start http://localhost:8501"

".venv\Scripts\python.exe" -m streamlit run app_demo.py --server.port=8501 --browser.gatherUsageStats=false

echo.
echo Service stopped.
pause

endlocal
