@echo off
setlocal
cd /d "%~dp0"

echo ========================================================
echo   Power ^& Memory Health Sentry - Windows 10 Launcher
echo ========================================================

:: Check Python installation
where python >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Python is not found in PATH!
    echo Please install Python 3.8 or newer from https://www.python.org/
    echo Make sure to check "Add Python to PATH" during installation.
    pause
    exit /b 1
)

:: Launch widget
start "" pythonw widget.py
if %ERRORLEVEL% equ 0 (
    echo [SUCCESS] Power ^& Memory Sentry widget launched successfully!
) else (
    echo [FALLBACK] Launching in standard console mode...
    python widget.py
)
endlocal
