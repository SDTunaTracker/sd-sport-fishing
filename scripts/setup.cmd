@echo off
REM One-time setup: create .venv and install Python dependencies. Pure CMD.
setlocal
set "ROOT=%~dp0.."
set "VENV=%ROOT%\.venv"
set "PYLAUNCHER=py"

where %PYLAUNCHER% >nul 2>nul
if errorlevel 1 (
    echo Python launcher 'py' not found. Install Python 3 from python.org first.
    pause
    exit /b 1
)

if not exist "%VENV%" (
    echo Creating venv at %VENV%
    %PYLAUNCHER% -3 -m venv "%VENV%"
    if errorlevel 1 (
        echo Failed to create venv.
        pause
        exit /b 1
    )
)

"%VENV%\Scripts\python.exe" -m pip install --upgrade pip
"%VENV%\Scripts\python.exe" -m pip install -r "%ROOT%\requirements.txt"

echo.
echo Setup complete. Next:
echo   scripts\run-daily.cmd     - one manual run
echo   scripts\serve.cmd         - view the dashboard
pause
