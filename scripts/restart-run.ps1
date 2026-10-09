# Restarts the round robin between two pairs, so it picks up a changed config (models joining or leaving) without
# losing a game in progress: waits for the next "pair N/M" line in the log, then presses the run monitor's Stop run
# and Start run. Needs the run monitor (scripts\monitor.ps1).
#   powershell -ExecutionPolicy Bypass -File scripts\restart-run.ps1
$root = Split-Path -Parent $PSScriptRoot
$log = Join-Path $root 'runs\roundrobin.log'
$monitor = 'http://127.0.0.1:8765'
$start = (Select-String -Path $log -Pattern '^pair ' | Measure-Object).Count
"Waiting for the next pair to start..."
while ((Select-String -Path $log -Pattern '^pair ' | Measure-Object).Count -le $start) { Start-Sleep 5 }
(Get-Content $log -Tail 1)
(Invoke-RestMethod -Method Post "$monitor/api/run/stop").message
Start-Sleep 3
(Invoke-RestMethod -Method Post "$monitor/api/run/start").message
