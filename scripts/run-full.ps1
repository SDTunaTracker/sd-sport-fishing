# Full daily run: scrape fish counts + SST + weather + Reddit + backtest.
# Runs once per day (registered separately from the 15-minute hourly scrape).
# Designed to be invoked by Task Scheduler; logs to logs/ with one file per run.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$logsDir = Join-Path $root "logs"
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $logsDir)) { New-Item -ItemType Directory -Path $logsDir | Out-Null }
$ts = Get-Date -Format "yyyyMMdd-HHmmss"
$logFile = Join-Path $logsDir "full-$ts.log"
Push-Location $root
try {
    "[$([DateTime]::Now.ToString('o'))] starting full daily run" | Out-File -FilePath $logFile -Encoding utf8
    & $py -m src.main 2>&1 | Tee-Object -FilePath $logFile -Append
    $exit = $LASTEXITCODE
    "[$([DateTime]::Now.ToString('o'))] exit=$exit" | Out-File -FilePath $logFile -Append -Encoding utf8
    exit $exit
} finally {
    Pop-Location
}
