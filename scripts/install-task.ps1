# Register scraper tasks with Windows Task Scheduler.
#
# Task 1 - "SD Sport Fishing - Hourly Scrape"
#   Runs every 15 minutes, 6am-10pm.
#   Uses --hourly flag: scrapes fish counts + schedules, exports data.js.
#   Completes in ~40s so it never hits the time limit.
#
# Task 2 - "SD Sport Fishing - Full Daily Run"
#   Runs once per day at 7:00am.
#   Full pipeline: SST + upwelling + chlorophyll + Reddit + backtest.
#   Time limit: 30 minutes.
[CmdletBinding()]
param(
    [string]$HourlyTaskName = "SD Sport Fishing - Hourly Scrape",
    [string]$FullTaskName   = "SD Sport Fishing - Full Daily Run"
)
$ErrorActionPreference = "Stop"
$root       = Split-Path -Parent $PSScriptRoot
$runHourly  = Join-Path $root "scripts\run-daily.ps1"
$runFull    = Join-Path $root "scripts\run-full.ps1"
if (-not (Test-Path $runHourly)) { Write-Error "run-daily.ps1 not found at $runHourly" }
if (-not (Test-Path $runFull))   { Write-Error "run-full.ps1 not found at $runFull" }

$userId = "$env:USERDOMAIN\$env:USERNAME"

# Remove old tasks (old name + new names) so this script is re-runnable.
foreach ($name in @($HourlyTaskName, $FullTaskName, "SD Sport Fishing - Daily Scrape")) {
    $existing = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    if ($existing) {
        Write-Output "Removing existing task '$name'"
        Unregister-ScheduledTask -TaskName $name -Confirm:$false
    }
}

# Task 1: 15-minute hourly scrape
$hourlyArgs = "-NoProfile -ExecutionPolicy Bypass -File `"$runHourly`""
$hourlyXml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Scrape fish counts every 15 min (6am-10pm), export data.js. Fast hourly-only run.</Description>
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
    <ExecutionTimeLimit>PT5M</ExecutionTimeLimit>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <StartWhenAvailable>true</StartWhenAvailable>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>powershell.exe</Command>
      <Arguments>$hourlyArgs</Arguments>
      <WorkingDirectory>$root</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"@

Register-ScheduledTask -TaskName $HourlyTaskName -Xml $hourlyXml -Force
Write-Output "Task '$HourlyTaskName' registered - runs every 15 min, 6am-10pm."

# Task 2: once-daily full run
$fullArgs = "-NoProfile -ExecutionPolicy Bypass -File `"$runFull`""
$fullXml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Full daily pipeline: SST, upwelling, chlorophyll, Reddit, backtest. Once per day at 7am.</Description>
  </RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>2000-01-01T07:00:00</StartBoundary>
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
    <ExecutionTimeLimit>PT30M</ExecutionTimeLimit>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <StartWhenAvailable>true</StartWhenAvailable>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>powershell.exe</Command>
      <Arguments>$fullArgs</Arguments>
      <WorkingDirectory>$root</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"@

Register-ScheduledTask -TaskName $FullTaskName -Xml $fullXml -Force
Write-Output "Task '$FullTaskName' registered - runs once daily at 7:00am."
Write-Output ""
Write-Output "To run the hourly scrape now: Start-ScheduledTask -TaskName '$HourlyTaskName'"
Write-Output "To run the full daily now:    Start-ScheduledTask -TaskName '$FullTaskName'"
