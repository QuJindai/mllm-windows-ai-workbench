[CmdletBinding()]
param()

$ErrorActionPreference='Stop'
Set-StrictMode -Version 2

$ProjectRoot=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$Bootstrap=Join-Path $ProjectRoot 'Bootstrap_SafeCore.ps1'
if(-not(Test-Path -LiteralPath $Bootstrap -PathType Leaf)){throw 'Bootstrap_SafeCore.ps1 missing'}

$stamp=Get-ChildItem -LiteralPath $ProjectRoot -Filter '.safe-core-materialized-*.stamp' -File -ErrorAction SilentlyContinue
foreach($item in @($stamp)){Remove-Item -LiteralPath $item.FullName -Force -ErrorAction SilentlyContinue}
foreach($relative in @('engine\Core.psm1','engine\EmergencyDoctor.ps1','gui\Workbench.Wpf.ps1')){
    $target=Join-Path $ProjectRoot $relative
    if(Test-Path -LiteralPath $target -PathType Leaf){Remove-Item -LiteralPath $target -Force}
}

& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Bootstrap
$rc=$LASTEXITCODE
if($rc -ne 0){throw "Direct Bootstrap_SafeCore.ps1 invocation failed rc=$rc"}

foreach($relative in @('engine\Core.psm1','engine\EmergencyDoctor.ps1','gui\Workbench.Wpf.ps1')){
    if(-not(Test-Path -LiteralPath (Join-Path $ProjectRoot $relative) -PathType Leaf)){
        throw "Direct bootstrap output missing: $relative"
    }
}
Write-Host 'DIRECT_BOOTSTRAP_SMOKE=PASS'
