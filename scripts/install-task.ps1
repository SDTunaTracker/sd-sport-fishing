# Register the hourly scrape with Windows Task Scheduler.
# Runs at the top of every hour between 6am and 10pm local time.
[CmdletBinding()]
param(
    [string]$TaskName = "SD Sport Fishing - Daily Scrape"
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$runDaily = Join-Path $root "scripts\run-daily.ps1"
if (-not (Test-Path $runDaily)) { Write-Error "run-daily.ps1 not found at $runDaily" }

# If the task already exists, remove it first so this script is re-runnable.
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Output "Removing existing task '$TaskName'"
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$runDaily`"" `
    -WorkingDirectory $root

# One trigger per hour, 6am through 10pm (17 triggers total).
$triggers = 6..22 | ForEach-Object {
    New-ScheduledTaskTrigger -Daily -At ("{0:D2}:00" -f $_)
}

# Run as the current user, only when logged in (no stored password required).
$principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive `
    -RunLevel Limited

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopIfGoingOnBatteries `
    -AllowStartIfOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 15)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $triggers `
    -Principal $principal `
    -Settings $settings `
    -Description "Scrape fish counts from the 4 SD landings hourly, 6am-10pm, and regenerate the dashboard data."

Write-Output ""
Write-Output "Task '$TaskName' registered. It will run hourly from 6:00am to 10:00pm."
Write-Output "To run it now: Start-ScheduledTask -TaskName '$TaskName'"
Write-Output "To remove it:  Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false"
