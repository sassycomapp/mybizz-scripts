$date = Get-Date -Format yyyy-MM-dd
$dest = "C:\backup-daily\$date"
New-Item -ItemType Directory -Force $dest | Out-Null

robocopy "C:\dev" "$dest\dev" /E /R:3 /W:5 /XD .git node_modules __pycache__ | Out-Null
robocopy "C:\mybizz" "$dest\mybizz" /E /R:3 /W:5 /XD .git node_modules __pycache__ | Out-Null