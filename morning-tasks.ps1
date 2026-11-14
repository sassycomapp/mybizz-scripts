# Morning tasks: runs at every Windows logon (Task Scheduler task MorningTasks) and runs only what is due.
#   Daily   (first logon of the day): daily copy of C:\dev and C:\mybizz; OpenCode history clean-up.
#   Weekly  (7 or more days after the last successful run): database backup and GBrain export; newest dumps copied to Google Drive.
#   Monthly (30 or more days after the last successful run): Ubuntu export to Google Drive. Never on the same morning as the weekly backup.
# Shows one pop-up only when a task failed or the weekly dream cycle is due. Writes one log line per task.
$ErrorActionPreference = 'Continue'
$Host.UI.RawUI.WindowTitle = 'Morning tasks running - do not open WSL yet'
$LogDir  = 'C:\mybizz\logs\morning-tasks'
$Log     = Join-Path $LogDir 'morning-tasks.log'
$State   = Join-Path $LogDir 'state.json'
$Drive   = 'G:\My Drive\mybizz-backups'
$DbLocal = 'C:\backup-gbrain'
New-Item -ItemType Directory -Force $LogDir | Out-Null
$today = (Get-Date).Date

function Write-Log($task, $result) {
  $line = "{0}  {1,-14} {2}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm'), $task, $result
  Add-Content -Path $Log -Value $line
  Write-Host $line
}
function Days-Since($value) {
  if (-not $value) { return 9999 }
  return ($today - [datetime]::ParseExact($value, 'yyyy-MM-dd', $null)).Days
}
function Wait-ForDrive {
  for ($i = 0; $i -lt 30; $i++) { if (Test-Path 'G:\My Drive') { return $true }; Start-Sleep -Seconds 10 }
  return $false
}

$s = @{ daily = $null; weekly = $null; monthly = $null }
if (Test-Path $State) { (Get-Content -Raw $State | ConvertFrom-Json).psobject.Properties | ForEach-Object { $s[$_.Name] = $_.Value } }
$problems = @()
$notes = @()
$todayText = $today.ToString('yyyy-MM-dd')

# ---------- Daily ----------
if ((Days-Since $s.daily) -ge 1) {
  Write-Host 'Daily copy of C:\dev and C:\mybizz ...'
  & powershell.exe -NoProfile -ExecutionPolicy Bypass -File 'C:\mybizz\scripts\daily-backup.ps1'
  $copyOk = ($LASTEXITCODE -eq 0)
  if ($copyOk) { Write-Log 'daily-copy' 'OK' } else { Write-Log 'daily-copy' "FAILED (exit $LASTEXITCODE)"; $problems += 'Daily copy of C:\dev and C:\mybizz failed.' }

  Write-Host 'OpenCode history clean-up ...'
  & wsl.exe bash /mnt/c/mybizz/scripts/opencode-session-prune.sh
  $pruneOk = ($LASTEXITCODE -eq 0)
  if ($pruneOk) { Write-Log 'opencode-prune' 'OK' } else { Write-Log 'opencode-prune' "FAILED (exit $LASTEXITCODE)"; $problems += 'OpenCode history clean-up failed.' }

  if ($copyOk -and $pruneOk) { $s.daily = $todayText }
}

# ---------- Weekly ----------
$weeklyRan = $false
if ((Days-Since $s.weekly) -ge 7) {
  $weeklyRan = $true
  Write-Host 'Weekly database backup and GBrain export (about 5 minutes) ...'
  & wsl.exe bash /mnt/c/mybizz/scripts/weekly-backup.sh
  if ($LASTEXITCODE -eq 0) {
    Write-Log 'weekly-backup' 'OK'
    $copied = $false
    if (Wait-ForDrive) {
      try {
        $dbDir = Join-Path $Drive 'database'
        New-Item -ItemType Directory -Force $dbDir | Out-Null
        $todayDumps = Get-ChildItem $DbLocal -Filter "*-$todayText.dump"
        if ($todayDumps.Count -ne 5) { throw 'expected 5 dumps' }
        $todayDumps | Copy-Item -Destination $dbDir -Force -ErrorAction Stop
        $dates = Get-ChildItem $dbDir -Filter '*.dump' | ForEach-Object { if ($_.Name -match '(\d{4}-\d{2}-\d{2})\.dump$') { $Matches[1] } } | Sort-Object -Unique -Descending
        $dates | Select-Object -Skip 2 | ForEach-Object { Remove-Item (Join-Path $dbDir "*-$_.dump") -Force }
        $copied = $true
      } catch { }
    }
    if ($copied) {
      Write-Log 'weekly-drive' 'OK'
      $s.weekly = $todayText
      $notes += 'The weekly backup is done. Today, in OpenCode (build mode): run /mb-memory-system-diagnostic and answer yes to the dream cycle at its end.'
    } else {
      Write-Log 'weekly-drive' 'FAILED'
      $problems += 'The weekly database copies could not be copied to Google Drive (G:\My Drive). Check that Google Drive is running, then log off and on again.'
    }
  } else {
    Write-Log 'weekly-backup' "FAILED (exit $LASTEXITCODE)"
    $problems += 'The weekly database backup failed. Its log is in C:\mybizz\logs\weekly-backup\. If PostgreSQL 15 is named there, start it: PowerShell (Admin): Start-Service postgresql-x64-15, then log off and on again. Answer NO to the dream cycle until the backup has succeeded.'
  }
}

# ---------- Monthly ----------
if (-not $weeklyRan -and (Days-Since $s.monthly) -ge 30) {
  Write-Host 'Monthly Ubuntu export to Google Drive (about 15 minutes). WSL is closed until it finishes ...'
  if (Wait-ForDrive) {
    New-Item -ItemType Directory -Force $Drive | Out-Null
    $tmp = Join-Path $Drive 'ubuntu-backup.tar.partial'
    $final = Join-Path $Drive 'ubuntu-backup.tar'
    & wsl.exe --shutdown
    & wsl.exe --export Ubuntu $tmp
    if ($LASTEXITCODE -eq 0 -and (Test-Path $tmp) -and ((Get-Item $tmp).Length -gt 1GB)) {
      Move-Item $tmp $final -Force
      Write-Log 'ubuntu-export' 'OK'
      $s.monthly = $todayText
    } else {
      Remove-Item $tmp -Force -ErrorAction SilentlyContinue
      Write-Log 'ubuntu-export' "FAILED (exit $LASTEXITCODE)"
      $problems += 'The monthly Ubuntu export failed. The previous export on Google Drive is unchanged. It is tried again at the next logon.'
    }
  } else {
    Write-Log 'ubuntu-export' 'FAILED (Google Drive not found)'
    $problems += 'The monthly Ubuntu export could not start: Google Drive (G:\My Drive) was not found. Check that Google Drive is running, then log off and on again.'
  }
}

$s | ConvertTo-Json | Set-Content -Path $State

# ---------- One pop-up, only when needed ----------
if ($problems.Count -gt 0 -or $notes.Count -gt 0) {
  $text = ''
  if ($problems.Count -gt 0) { $text += "PROBLEMS:`r`n" + ($problems -join "`r`n`r`n") + "`r`n`r`nIf a problem stays after logging on again, paste C:\mybizz\logs\morning-tasks\morning-tasks.log to Claude.`r`n`r`n" }
  if ($notes.Count -gt 0) { $text += "TO DO TODAY:`r`n" + ($notes -join "`r`n") }
  Add-Content -Path $Log -Value ($text -split "`r`n" | ForEach-Object { "                  $_" })
  $Host.UI.RawUI.WindowTitle = 'Morning tasks finished - read the pop-up'
  Write-Host ''
  Write-Host 'Finished. Read the pop-up and click OK.'
  Add-Type -AssemblyName System.Windows.Forms
  $owner = New-Object System.Windows.Forms.Form
  $owner.TopMost = $true
  $owner.ShowInTaskbar = $false
  $owner.StartPosition = 'CenterScreen'
  $owner.Opacity = 0
  $owner.Show()
  $owner.Activate()
  [System.Windows.Forms.MessageBox]::Show($owner, $text, 'Morning tasks') | Out-Null
  $owner.Close()
}
