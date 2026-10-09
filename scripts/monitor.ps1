# Starts the run monitor (http://<this PC>:8765/) with no window, outside the terminal or app that runs this script,
# so closing them doesn't stop it. Its page has the buttons to start and stop runs and to stop the monitor itself.
#   powershell -ExecutionPolicy Bypass -File scripts\monitor.ps1
$root = Split-Path -Parent $PSScriptRoot
$port = 8765
if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
    "The run monitor is already running: http://localhost:$port/"
    exit 0
}
$uv = (Get-Command uv -ErrorAction Stop).Source
# Win32_Process.Create starts it under Windows' WMI host (not as a child of this shell); ShowWindow 0 hides its console.
$startup = New-CimInstance -ClassName Win32_ProcessStartup -ClientOnly -Property @{ ShowWindow = [uint16]0 }
$result = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
    CommandLine = "`"$uv`" run rotomarena dashboard --port $port"
    CurrentDirectory = $root
    ProcessStartupInformation = $startup
}
if ($result.ReturnValue -ne 0) { throw "Could not start the run monitor (Win32_Process.Create returned $($result.ReturnValue))." }
$ip = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.PrefixOrigin -in 'Dhcp', 'Manual' -and $_.IPAddress -notlike '169.*' -and
       $_.InterfaceAlias -notmatch 'Tailscale|vEthernet|Loopback' } | Select-Object -First 1).IPAddress
"Run monitor starting: http://localhost:$port/ (on the LAN: http://${ip}:$port/)"
