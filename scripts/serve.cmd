@echo off
REM Launch the SD Sport Fishing dashboard locally.
REM Pure CMD (no PowerShell) so corporate script-blocking policies leave it alone.
setlocal
set "ROOT=%~dp0.."
set "WEB=%ROOT%\web"
set "PY=%ROOT%\.venv\Scripts\python.exe"

if not exist "%PY%" (
    echo Python venv not found at %PY%.
    echo Run scripts\setup.cmd first.
    pause
    exit /b 1
)

REM Open the browser, then start the server (server blocks this window).
start "" "http://localhost:8765/SD%%20Sport%%20Fishing.html"
cd /d "%WEB%"
"%PY%" -m http.server 8765
