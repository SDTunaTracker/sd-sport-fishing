# Keep the private AIS position archive (src/ais_archive.py) running.
#
# Registers "TunaTracker - AIS Archive": starts at logon and re-checks every
# 15 minutes; if the listener already runs, the new start is ignored, so a
# crash or sleep costs at most 15 minutes. The archive lives outside the repo
# at %LOCALAPPDATA%\TunaTracker\ais_archive.db (never committed or published).
#
# Run once, from the main checkout, after this script's branch is on main:
#   powershell -ExecutionPolicy Bypass -File scripts\install-ais-archive-task.ps1
# Uninstall:
#   Unregister-ScheduledTask -TaskName "TunaTracker - AIS Archive" -Confirm:$false

$taskName    = "TunaTracker - AIS Archive"
$projectRoot = $PSScriptRoot | Split-Path -Parent
$pythonw     = Join-Path $projectRoot ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $pythonw)) { throw "Missing $pythonw (create the venv first)" }

$action   = New-ScheduledTaskAction -Execute $pythonw -Argument "-m src.ais_archive" `
                -WorkingDirectory $projectRoot
$atLogon  = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$every15  = New-ScheduledTaskTrigger -Once -At (Get-Date) `
                -RepetitionInterval (New-TimeSpan -Minutes 15)
$settings = New-ScheduledTaskSettingsSet `
                -ExecutionTimeLimit ([TimeSpan]::Zero) `
                -MultipleInstances IgnoreNew `
                -StartWhenAvailable `
                -RunOnlyIfNetworkAvailable `
                -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger @($atLogon, $every15) `
    -Settings $settings -Force | Out-Null

Write-Host "Task '$taskName' installed (at logon + every 15 min, one instance)." -ForegroundColor Green
Write-Host "Status: .venv\Scripts\python.exe -m src.ais_archive --status"
