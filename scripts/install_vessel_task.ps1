# Install Windows Task Scheduler task to run the AIS push script every 5 minutes.
# Run as Administrator once:
#   powershell -ExecutionPolicy Bypass -File scripts\install_vessel_task.ps1

$taskName    = "TunaTracker-AIS-Push"
$projectRoot = $PSScriptRoot | Split-Path -Parent
$python      = Join-Path $projectRoot ".venv\Scripts\python.exe"
$script      = Join-Path $projectRoot "scripts\ais_push.py"
$logFile     = Join-Path $projectRoot "logs\ais_push.log"

# Ensure logs directory exists
New-Item -ItemType Directory -Force -Path (Split-Path $logFile) | Out-Null

$action  = New-ScheduledTaskAction `
    -Execute $python `
    -Argument "--duration 45 >> `"$logFile`" 2>&1" `
    -WorkingDirectory $projectRoot

# Repeating trigger: every 5 minutes, starting now, indefinitely
$trigger = New-ScheduledTaskTrigger -RepetitionInterval (New-TimeSpan -Minutes 5) `
    -Once -At (Get-Date)

$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 2) `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew

Register-ScheduledTask `
    -TaskName $taskName `
    -Action   $action `
    -Trigger  $trigger `
    -Settings $settings `
    -RunLevel Highest `
    -Force | Out-Null

Write-Host "Task '$taskName' installed — runs every 5 minutes." -ForegroundColor Green
Write-Host "Log: $logFile"
Write-Host ""
Write-Host "To run manually now: Start-ScheduledTask -TaskName '$taskName'"
Write-Host "To uninstall:        Unregister-ScheduledTask -TaskName '$taskName' -Confirm:`$false"
