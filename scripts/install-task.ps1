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

# Register via XML — the only reliable way to set a repetition interval on a
# daily trigger in PowerShell 5.1. The CalendarTrigger fires at 06:00 each day
# and repeats every 15 minutes (PT15M) for 16 hours (PT16H, ending at 22:00).
$userId = "$env:USERDOMAIN\$env:USERNAME"
$taskXml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Scrape trip availability from the 4 SD landings every 15 minutes, 6am-10pm, and regenerate the dashboard data.</Description>
  </RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <Repetition>
        <Interval>PT15M</Interval>
        <Duration>PT16H</Duration>
        <StopAtDurationEnd>false</StopAtDurationEnd>
      </Repetition>
      <StartBoundary>2000-01-01T06:00:00</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByDay>
        <DaysInterval>1</DaysInterval>
      </ScheduleByDay>
    </CalendarTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>$userId</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <ExecutionTimeLimit>PT10M</ExecutionTimeLimit>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <StartWhenAvailable>true</StartWhenAvailable>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>powershell.exe</Command>
      <Arguments>-NoProfile -ExecutionPolicy Bypass -File "$runDaily"</Arguments>
      <WorkingDirectory>$root</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"@

Register-ScheduledTask -TaskName $TaskName -Xml $taskXml -Force

Write-Output ""
Write-Output "Task '$TaskName' registered. It will run every 15 minutes from 6:00am to 10:00pm."
Write-Output "To run it now: Start-ScheduledTask -TaskName '$TaskName'"
Write-Output "To remove it:  Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false"
