# Keeps trying to draft a model whose provider is down (say a free endpoint that answers 502) until a draft is kept,
# then restarts the run at its next pair so the model joins (scripts\restart-run.ps1). Tries every -Minutes, for up to
# -Hours. It starts itself again hidden, outside the terminal or app that runs it. Log: runs\retry-draft-<id>.log.
#   powershell -ExecutionPolicy Bypass -File scripts\retry-draft.ps1 -Id nemotron_3_ultra
param([Parameter(Mandatory)][string]$Id, [int]$Minutes = 30, [int]$Hours = 48, [switch]$Detached)
$root = Split-Path -Parent $PSScriptRoot
$uv = (Get-Command uv -ErrorAction Stop).Source
if (-not $Detached) {
    $startup = New-CimInstance -ClassName Win32_ProcessStartup -ClientOnly -Property @{ ShowWindow = [uint16]0 }
    $result = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
        CommandLine = "powershell -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Id $Id -Minutes $Minutes -Hours $Hours -Detached"
        CurrentDirectory = $root
        ProcessStartupInformation = $startup
    }
    if ($result.ReturnValue -ne 0) { throw "Could not start the retries (Win32_Process.Create returned $($result.ReturnValue))." }
    "Retrying the $Id draft every $Minutes min for up to $Hours h; follow runs\retry-draft-$Id.log"
    exit 0
}
$out = Join-Path $root "runs\retry-draft-$Id.log"
function Note($text) { "$(Get-Date -Format 'yyyy-MM-dd HH:mm') $text" | Add-Content $out -Encoding UTF8 }
Set-Location $root
$deadline = (Get-Date).AddHours($Hours)
while ((Get-Date) -lt $deadline) {
    Note "drafting $Id"
    # cmd's redirection keeps Python's UTF-8 as it is (PowerShell's would write UTF-16)
    cmd /c "set PYTHONIOENCODING=utf-8&& `"$uv`" run rotomarena teams draft $Id >> `"$out`" 2>&1"
    # Kept a draft under the version being played?
    & $uv run python -c "import sys; from rotomarena.config import AppConfig; from rotomarena.teams.draft import load_drafts; c = AppConfig.load('config.yaml'); sys.exit(0 if load_drafts(version=c.ruleset.version, fmt=c.ruleset.format).get('$Id') else 1)"
    if ($LASTEXITCODE -eq 0) {
        Note "draft kept; restarting the run at its next pair so $Id joins"
        & powershell -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'restart-run.ps1') *>&1 |
            ForEach-Object { Note $_ }
        exit 0
    }
    Start-Sleep -Seconds ($Minutes * 60)
}
Note "gave up after $Hours h"
