# Daily live shadow run for the forecast R&D model (research only; never touches the site).
# Reads tracker.db read-only (SQLite backup snapshot); writes only to this folder.
# Registered as Windows scheduled task "TunaTracker Forecast Shadow" (daily 07:45, after the 06:30 scrape).
# Remove with:  schtasks /Delete /TN "TunaTracker Forecast Shadow" /F
$ErrorActionPreference = "Continue"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$rf   = Split-Path -Parent $here
$py   = Join-Path $rf ".venv\Scripts\python.exe"
$log  = Join-Path $here "run.log"
Set-Location $rf
"==== $(Get-Date -Format s) issue ====" | Out-File -Append -Encoding utf8 $log
& $py -u shadow.py issue *>&1 | Where-Object { $_ -notmatch "Warning|^\s+d\[|^\s+t\[" } | Out-File -Append -Encoding utf8 $log
"exit $LASTEXITCODE" | Out-File -Append -Encoding utf8 $log
# H3 booking-velocity history (research only; separate from the frozen model, not in code_hash)
& $py -u shadow\snap_schedule.py *>&1 | Out-File -Append -Encoding utf8 $log
# Parallel r5 candidate shadow (separate log; the frozen r4 above is untouched)
& $py -u shadow_r5.py issue *>&1 | Where-Object { $_ -notmatch "Warning|^\s+d\[|^\s+t\[" } | Out-File -Append -Encoding utf8 $log
# Data freshness guard (tracker.db may move to R2; the laptop copy could go stale)
& $py -u shadow\check_fresh.py *>&1 | Out-File -Append -Encoding utf8 $log
