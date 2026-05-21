# Register the daily scrape with Windows Task Scheduler.
# Runs at 06:30 local time every day. Adjust -TaskTime to change.
[CmdletBinding()]
param(
    [string]$TaskName = "SD Sport Fishing - Daily Scrape",
    [string]$TaskTime = "06:30"
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

$trigger = New-ScheduledTaskTrigger -Daily -At $TaskTime

# Run as the current user, only when logged in (no stored password required).
# If you want it to run when you're not logged in, swap in:
#   -User "$env:USERDOMAIN\$env:USERNAME" -Password (Read-Host -AsSecureString) `
#   -LogonType Password
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
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Description "Scrape yesterday's fish counts from the 4 SD landings and regenerate the dashboard data."

Write-Output ""
Write-Output "Task '$TaskName' registered. It will run daily at $TaskTime."
Write-Output "To run it now: Start-ScheduledTask -TaskName '$TaskName'"
Write-Output "To remove it:  Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false"
