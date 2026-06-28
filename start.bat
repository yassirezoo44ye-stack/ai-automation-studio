@echo off
title AI Automation Studio
color 0A
chcp 65001 >nul

echo.
echo  ====================================
echo   AI Automation Studio  v3.0
echo   Powered by Claude
echo  ====================================
echo.

:: Load .env
if not exist ".env" (
    echo [ERROR] .env not found. Create it with ANTHROPIC_API_KEY and DATABASE_URL
    pause & exit /b 1
)
for /f "tokens=1,* delims==" %%a in (.env) do (
    if not "%%a"=="" set %%a=%%b
)

:: Build frontend if dist missing
if not exist "dist\index.html" (
    echo [1/3] Building frontend...
    call npm run build
    if errorlevel 1 ( echo Build failed! & pause & exit /b 1 )
    echo [1/3] Frontend ready.
) else (
    echo [1/3] Frontend dist OK.
)

:: Kill old backend
echo [2/3] Stopping any old server...
for /f "tokens=5" %%p in ('netstat -ano 2^>nul ^| findstr ":8000.*LISTENING"') do (
    taskkill /PID %%p /F >nul 2>&1
)
timeout /t 1 /nobreak >nul

:: Start backend (serves frontend too)
echo [3/3] Starting server...
start "AI Studio" /min python main.py

:: Wait until healthy
:wait
timeout /t 2 /nobreak >nul
curl -s http://127.0.0.1:8000/health >nul 2>&1
if errorlevel 1 goto wait

echo.
echo  ====================================
echo   Ready!  http://localhost:8000
echo   Docs:   http://localhost:8000/docs
echo  ====================================
echo.

start http://localhost:8000
echo  Press any key to stop the server...
pause >nul

:: Cleanup
for /f "tokens=5" %%p in ('netstat -ano 2^>nul ^| findstr ":8000.*LISTENING"') do (
    taskkill /PID %%p /F >nul 2>&1
)
echo Server stopped.
