@echo off
REM Flow Agent — Windows Uninstaller
REM
REM Usage: uninstall.bat
REM
REM Removes startup entry and optionally deletes the installed files.

setlocal EnableDelayedExpansion

set "INSTALL_DIR=%LOCALAPPDATA%\FlowAgent\app"
set "EXE_NAME=flow-agent.exe"
set "EXE_PATH=%INSTALL_DIR%\%EXE_NAME%"

echo Flow Agent Uninstaller
echo ======================

if exist "%EXE_PATH%" (
    echo Removing startup entry ...
    "%EXE_PATH%" remove-startup
    echo Clearing agent session ...
    "%EXE_PATH%" clear
)

echo Removing files from %INSTALL_DIR% ...
if exist "%INSTALL_DIR%" (
    rd /s /q "%INSTALL_DIR%"
)

echo.
echo Flow Agent has been uninstalled.

endlocal
exit /b 0
