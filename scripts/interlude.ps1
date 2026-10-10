# Plays another version's round robin in a break of the run (say a best of three's deciding game in an older
# benchmark): waits for the run's next "pair N/M" line, presses the run monitor's Stop run, plays the other version
# once the run is down (output in runs\interlude.log), then presses Start run. With no run going it plays at once.
# It starts itself again hidden, outside the terminal or app that runs it, so closing them doesn't leave the run
# stopped. Needs the run monitor (scripts\monitor.ps1).
#   powershell -ExecutionPolicy Bypass -File scripts\interlude.ps1 -Version s4
param([Parameter(Mandatory)][string]$Version, [switch]$Detached)
$root = Split-Path -Parent $PSScriptRoot
$uv = (Get-Command uv -ErrorAction Stop).Source
if (-not $Detached) {
    $startup = New-CimInstance -ClassName Win32_ProcessStartup -ClientOnly -Property @{ ShowWindow = [uint16]0 }
    $result = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
        CommandLine = "powershell -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Version $Version -Detached"
        CurrentDirectory = $root
        ProcessStartupInformation = $startup
    }
    if ($result.ReturnValue -ne 0) { throw "Could not start the interlude (Win32_Process.Create returned $($result.ReturnValue))." }
    "Interlude started: $Version plays at the run's next pair (at once if no run is going); follow runs\interlude.log"
    exit 0
}
$log = Join-Path $root 'runs\roundrobin.log'
$out = Join-Path $root 'runs\interlude.log'
$monitor = 'http://127.0.0.1:8765'
function Note($text) { "$(Get-Date -Format 'yyyy-MM-dd HH:mm') $text" | Add-Content $out -Encoding UTF8 }
function Run() { (Invoke-RestMethod "$monitor/api/status").run }
if ((Run).running) {
    $start = (Select-String -Path $log -Pattern '^pair ' | Measure-Object).Count
    Note "waiting for the run's next pair to play $Version"
    while ((Select-String -Path $log -Pattern '^pair ' | Measure-Object).Count -le $start) { Start-Sleep 5 }
    Note (Invoke-RestMethod -Method Post "$monitor/api/run/stop").message
}
# The stopped run's driver publishes before it exits, and Showdown takes a moment to go: play once both are gone
for ($i = 0; $i -lt 60; $i++) { $r = Run; if (-not $r.running -and -not $r.showdown_running) { break }; Start-Sleep 5 }
Start-Sleep 5
Note "playing $Version"
# cmd's redirection keeps Python's UTF-8 as it is (PowerShell's would write UTF-16 and wrap stderr as errors)
cmd /c "set PYTHONIOENCODING=utf-8&& `"$uv`" run rotomarena ladder round-robin --version $Version --games-per-pair 2 >> `"$out`" 2>&1"
Note "$Version done (exit code $LASTEXITCODE)"
for ($i = 0; $i -lt 60; $i++) { if (-not (Run).showdown_running) { break }; Start-Sleep 5 }
Note (Invoke-RestMethod -Method Post "$monitor/api/run/start").message
