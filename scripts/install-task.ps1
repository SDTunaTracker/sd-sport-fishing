# Register the scraper with Windows Task Scheduler.
# Runs every 15 minutes between 6am and 10pm local time.
#
# Why 15 minutes: none of the 4 landings expose a real-time booking API —
# H&M uses Xola (xolacache JSONP, no public API key), FL/Seaforth/Point Loma
# use fishingreservations.net (HTML-only, no API). More frequent scraping is
# the best available substitute for real-time availability data.
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

# Every 15 minutes, 6:00am through 10:00pm (65 triggers: :00/:15/:30/:45 each
# hour for 6-21, plus the final 22:00 trigger).
$triggers = [System.Collections.Generic.List[object]]::new()
for ($h = 6; $h -le 22; $h++) {
    $maxMinute = if ($h -eq 22) { 0 } else { 45 }
    for ($m = 0; $m -le $maxMinute; $m += 15) {
        $triggers.Add(
            (New-ScheduledTaskTrigger -Daily -At ("{0:D2}:{1:D2}" -f $h, $m))
        )
    }
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
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $triggers.ToArray() `
    -Principal $principal `
    -Settings $settings `
    -Description "Scrape trip availability from the 4 SD landings every 15 minutes, 6am-10pm, and regenerate the dashboard data."

Write-Output ""
Write-Output "Task '$TaskName' registered. It will run every 15 minutes from 6:00am to 10:00pm."
Write-Output "To run it now: Start-ScheduledTask -TaskName '$TaskName'"
Write-Output "To remove it:  Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false"
