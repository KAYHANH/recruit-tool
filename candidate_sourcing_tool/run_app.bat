@echo off
title Candidate Finder Launcher
setlocal
cd /d "%~dp0"

echo ===================================================
echo     Candidate Finder - Modern Web Application
echo         (FastAPI Backend + React Frontend)
echo              Strict Rs. 0 Budget Guarantee
echo ===================================================
echo.

:: 1. Check Python
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Python not found on PATH. Please install Python 3.10+
    pause
    exit /b 1
)

:: 2. Check Node / npm
where npm >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Node.js / npm not found on PATH. Please install Node.js 18+
    pause
    exit /b 1
)

echo [1/3] Starting FastAPI Backend on http://127.0.0.1:8000 ...
start "Candidate Finder Backend (FastAPI)" cmd /c "python -m uvicorn api:app --host 127.0.0.1 --port 8000 --reload"

echo [2/3] Starting React Vite Frontend on http://localhost:5173 ...
start "Candidate Finder Frontend (Vite)" cmd /c "cd frontend && npm run dev"

echo [3/3] Waiting for servers to initialize...
timeout /t 3 /nobreak >nul

echo.
echo ===================================================
echo  Services Running:
echo    - Frontend UI:  http://localhost:5173
echo    - Backend API:  http://127.0.0.1:8000
echo    - API Swagger:  http://127.0.0.1:8000/docs
echo ===================================================
echo.
echo Opening browser...
start http://localhost:5173

echo.
echo Press any key to stop all Candidate Finder background windows...
pause >nul

:: Terminate running processes
taskkill /fi "WINDOWTITLE eq Candidate Finder Backend*" /f >nul 2>nul
taskkill /fi "WINDOWTITLE eq Candidate Finder Frontend*" /f >nul 2>nul

echo Done.
endlocal
