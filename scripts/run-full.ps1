# Full daily run: scrape fish counts + SST + weather + Reddit + backtest + export.
# Runs once per day (separate from the 15-minute hourly task).
# Designed to be invoked by Task Scheduler; logs to logs/ with one file per run.
#
# IMPORTANT: Do NOT use "2>&1" when $ErrorActionPreference = "Stop".
# In PowerShell 5.1, 2>&1 wraps native stderr as ErrorRecord objects and
# $ErrorActionPreference=Stop then kills the pipeline on the first log line.
# Fix: pipe stdout only (no 2>&1); stderr stays on the console.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$logsDir = Join-Path $root "logs"
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $logsDir)) { New-Item -ItemType Directory -Path $logsDir | Out-Null }
$ts = Get-Date -Format "yyyyMMdd-HHmmss"
$logFile = Join-Path $logsDir "full-$ts.log"
Push-Location $root
try {
    $utf8 = New-Object System.Text.UTF8Encoding $false
    $writer = New-Object System.IO.StreamWriter($logFile, $false, $utf8)
    try {
        $writer.WriteLine("[$([DateTime]::Now.ToString('o'))] starting full daily run")
        $writer.Flush()
        & $py -m src.main | ForEach-Object {
            Write-Output $_
            $writer.WriteLine($_)
        }
        $exit = $LASTEXITCODE
        $writer.WriteLine("[$([DateTime]::Now.ToString('o'))] exit=$exit")
    } finally {
        $writer.Dispose()
    }
    exit $exit
} catch {
    Add-Content -Path $logFile -Encoding utf8 -Value "[$([DateTime]::Now.ToString('o'))] FATAL: $_"
    exit 1
} finally {
    Pop-Location
}
