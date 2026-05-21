@echo off
REM Daily scrape wrapper. CMD-only so corporate script-blocking doesn't trip on it.
setlocal
set "ROOT=%~dp0.."
set "PY=%ROOT%\.venv\Scripts\python.exe"
set "LOGS=%ROOT%\logs"

if not exist "%LOGS%" mkdir "%LOGS%"
for /f "tokens=2 delims==" %%I in ('wmic os get localdatetime /value 2^>nul ^| find "="') do set "DT=%%I"
set "TS=%DT:~0,8%-%DT:~8,6%"
set "LOG=%LOGS%\run-%TS%.log"

cd /d "%ROOT%"
echo [%DATE% %TIME%] starting daily run >> "%LOG%"
"%PY%" -m src.main >> "%LOG%" 2>&1
set "EXIT=%ERRORLEVEL%"
echo [%DATE% %TIME%] exit=%EXIT% >> "%LOG%"
exit /b %EXIT%
