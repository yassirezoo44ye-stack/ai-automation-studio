@echo off
title AI Automation Studio
color 0A
echo.
echo  =====================================
echo   AI Automation Studio - Starting...
echo  =====================================
echo.

:: Load env from .env file
for /f "tokens=1,* delims==" %%a in (.env) do (
    if not "%%a"=="" if not "%%a:~0,1%"=="#" set %%a=%%b
)

:: Start backend
echo [1/2] Starting FastAPI backend on port 8000...
start "AI Studio Backend" /min python main.py

:: Wait for backend
timeout /t 6 /nobreak >nul
echo [1/2] Backend ready.

:: Start frontend
echo [2/2] Starting React frontend on port 3000...
start "AI Studio Frontend" /min cmd /c npm run dev

timeout /t 5 /nobreak >nul
echo [2/2] Frontend ready.
echo.
echo  =====================================
echo   App running at http://localhost:3000
echo   API docs at  http://localhost:8000/docs
echo  =====================================
echo.

:: Open browser
start http://localhost:3000

echo  Press any key to stop all servers...
pause >nul

:: Cleanup
taskkill /fi "WINDOWTITLE eq AI Studio Backend*" /f >nul 2>&1
taskkill /fi "WINDOWTITLE eq AI Studio Frontend*" /f >nul 2>&1
echo Servers stopped.
