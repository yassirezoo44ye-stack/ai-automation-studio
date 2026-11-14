@echo off
REM Flow Agent — Windows Installer
REM
REM Usage: install.bat
REM
REM Installs flow-agent.exe to %LOCALAPPDATA%\FlowAgent and registers
REM the agent to start automatically at Windows login.

setlocal EnableDelayedExpansion

set "INSTALL_DIR=%LOCALAPPDATA%\FlowAgent\app"
set "EXE_NAME=flow-agent.exe"
set "EXE_SRC=%~dp0dist\%EXE_NAME%"

echo Flow Agent Installer
echo ====================

if not exist "%EXE_SRC%" (
    echo ERROR: Could not find %EXE_SRC%
    echo Please build the agent first: py -3.11 build.py
    exit /b 1
)

echo Installing to %INSTALL_DIR% ...
if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"

copy /Y "%EXE_SRC%" "%INSTALL_DIR%\%EXE_NAME%" >nul
if errorlevel 1 (
    echo ERROR: Failed to copy %EXE_NAME%
    exit /b 1
)

echo Registering startup entry ...
"%INSTALL_DIR%\%EXE_NAME%" startup "%INSTALL_DIR%"
if errorlevel 1 (
    echo WARNING: Could not register startup entry.
)

echo.
echo Flow Agent installed successfully.
echo Location: %INSTALL_DIR%\%EXE_NAME%
echo The agent will start automatically at next login.
echo.
echo To connect, run:
echo   %INSTALL_DIR%\%EXE_NAME% enroll --server wss://YOUR-FLOW-SERVER/ws/agent

endlocal
exit /b 0
