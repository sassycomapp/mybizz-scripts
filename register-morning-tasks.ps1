# Run once, in PowerShell (Admin): creates the MorningTasks task and removes the tasks it replaces.
# MorningTasks runs C:\mybizz\scripts\morning-tasks.ps1 one minute after this user logs on to Windows.
$user = "$env:USERDOMAIN\$env:USERNAME"

foreach ($old in 'SundayBackup', 'DailyDevBackup', 'OpenCodeSessionPrune', 'MissedRunCheck') {
  if (Get-ScheduledTask -TaskName $old -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $old -Confirm:$false
    "removed  $old"
  } else { "absent   $old" }
}

$action   = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument '-NoProfile -ExecutionPolicy Bypass -File C:\mybizz\scripts\morning-tasks.ps1'
$trigger  = New-ScheduledTaskTrigger -AtLogOn -User $user
$trigger.Delay = 'PT1M'
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 2) -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName 'MorningTasks' -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
"created  MorningTasks"

# The monthly Ubuntu export was last done by hand on 2026-11-14.
$dir = 'C:\mybizz\logs\morning-tasks'
New-Item -ItemType Directory -Force $dir | Out-Null
if (-not (Test-Path "$dir\state.json")) {
  @{ daily = $null; weekly = $null; monthly = '2026-11-14' } | ConvertTo-Json | Set-Content "$dir\state.json"
  "seeded   state.json"
}
