Add-Type -AssemblyName System.Windows.Forms
$t = Get-Content -Raw 'C:\mybizz\logs\sunday-backup\last-result.txt'
[System.Windows.Forms.MessageBox]::Show($t, 'Sunday maintenance') | Out-Null
