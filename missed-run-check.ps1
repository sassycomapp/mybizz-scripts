# Missed-run check: runs at logon. Shows one message if a scheduled task is overdue or its last run did not finish.
param([int]$TestMaxHours = 0)
$checks = @(
  @{ Name = 'DailyDevBackup';       MaxHours = 26;  Ok = @(0,1,2,3,4,5,6,7) },   # robocopy: 0-7 = success
  @{ Name = 'OpenCodeSessionPrune'; MaxHours = 26;  Ok = @(0) },
  @{ Name = 'SundayBackup';         MaxHours = 170; Ok = @(0) }
)
$problems = @()
foreach ($c in $checks) {
  $max = if ($TestMaxHours -gt 0) { $TestMaxHours } else { $c.MaxHours }
  $i = Get-ScheduledTaskInfo -TaskName $c.Name -ErrorAction SilentlyContinue
  if (-not $i) { $problems += "$($c.Name): task not found"; continue }
  $r = [int64]$i.LastTaskResult
  if ($r -eq 267009) { continue }   # running now
  if ($i.LastRunTime -lt (Get-Date).AddHours(-$max)) { $problems += "$($c.Name): missed - last run $($i.LastRunTime)" }
  elseif ($c.Ok -notcontains $r) { $problems += "$($c.Name): did not finish - result $r" }
}
if ($problems.Count -eq 0) { 'No missed runs' } else { $problems | ForEach-Object { "MISSED  $_" } }
if ($problems.Count -gt 0) {
  Add-Type -AssemblyName System.Windows.Forms
  [System.Windows.Forms.MessageBox]::Show(($problems -join "`r`n"), 'Missed scheduled runs') | Out-Null
}
