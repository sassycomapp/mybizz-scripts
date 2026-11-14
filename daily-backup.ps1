# Daily copy of C:\dev and C:\mybizz into C:\backup-daily\<date>, without Git history or build folders.
# Keeps the three most recent copies. Older copies are deleted only after today's copy succeeded.
# Run by morning-tasks.ps1. Exit 0 = copy done; exit 1 = copy failed (nothing deleted).
$root = 'C:\backup-daily'
$date = Get-Date -Format yyyy-MM-dd
$dest = Join-Path $root $date
New-Item -ItemType Directory -Force $dest | Out-Null
robocopy "C:\dev" "$dest\dev" /E /R:3 /W:5 /XD .git node_modules __pycache__ | Out-Null
$a = $LASTEXITCODE
robocopy "C:\mybizz" "$dest\mybizz" /E /R:3 /W:5 /XD .git node_modules __pycache__ | Out-Null
$b = $LASTEXITCODE
if ($a -ge 8 -or $b -ge 8) { exit 1 }   # robocopy: 0-7 = success, 8 or more = failure
Get-ChildItem $root -Directory | Where-Object { $_.Name -match '^\d{4}-\d{2}-\d{2}$' } |
  Sort-Object Name -Descending | Select-Object -Skip 3 | Remove-Item -Recurse -Force
exit 0
