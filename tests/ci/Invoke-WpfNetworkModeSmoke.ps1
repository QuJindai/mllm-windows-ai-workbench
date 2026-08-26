[CmdletBinding()]
param()
$ErrorActionPreference='Stop'
$Root=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path

python (Join-Path $Root 'ci\materialize.py')
if($LASTEXITCODE -ne 0){throw "materialize failed rc=$LASTEXITCODE"}

$out=@(& powershell.exe -NoProfile -STA -ExecutionPolicy Bypass -File (Join-Path $Root 'gui\Workbench.Wpf.ps1') -ProjectRoot $Root -DataRoot (Join-Path $env:RUNNER_TEMP 'mllm-wpf-network-mode') -NetworkMode OFFLINE_CACHE -SmokeTest 2>&1)
$rc=$LASTEXITCODE
$text=($out -join "`n")
Write-Host $text
if($rc -ne 0){throw "WPF network mode smoke failed rc=$rc"}
if($text -notmatch 'WPF_SMOKE=PASS network_mode=OFFLINE_CACHE'){
    throw "WPF did not honor requested initial NetworkMode=OFFLINE_CACHE. Output: $text"
}
Write-Host 'WPF_NETWORK_MODE_SMOKE=PASS'
