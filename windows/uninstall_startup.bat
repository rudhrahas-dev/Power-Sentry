@echo off
setlocal

echo ========================================================
echo   Power ^& Memory Sentry - Windows 10 Autostart Uninstaller
echo ========================================================

set "STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "SHORTCUT_PATH=%STARTUP_DIR%\PowerSentry.vbs"

if exist "%SHORTCUT_PATH%" (
    del /f /q "%SHORTCUT_PATH%"
    echo.
    echo [SUCCESS] Removed PowerSentry from Windows Startup.
    echo.
) else (
    echo.
    echo [INFO] PowerSentry was not found in the Startup folder.
    echo.
)

pause
endlocal
