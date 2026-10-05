@echo off
setlocal
cd /d "%~dp0"

echo ========================================================
echo   Power ^& Memory Sentry - Windows 10 Autostart Installer
echo ========================================================

set "STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "SHORTCUT_PATH=%STARTUP_DIR%\PowerSentry.vbs"

echo [*] Target Startup Folder: "%STARTUP_DIR%"

if not exist "%STARTUP_DIR%" (
    echo [ERROR] Could not locate Windows Startup directory.
    pause
    exit /b 1
)

:: Create startup runner pointing to launch.vbs in this directory
(
echo ' Autostart Runner for Power ^& Memory Sentry
echo Set objShell = CreateObject^("WScript.Shell"^)
echo objShell.CurrentDirectory = "%~dp0"
echo objShell.Run "wscript.exe """ ^& "%~dp0launch.vbs"""", 0, False
) > "%SHORTCUT_PATH%"

if exist "%SHORTCUT_PATH%" (
    echo.
    echo [SUCCESS] Power ^& Memory Sentry has been configured to start
    echo           automatically whenever you log into Windows!
    echo.
    echo [*] Startup script installed to:
    echo     %SHORTCUT_PATH%
    echo.
) else (
    echo [ERROR] Failed to write startup runner script.
)

pause
endlocal
