[CmdletBinding()]
param()
$ErrorActionPreference='Stop'
$ProjectRoot=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path

python (Join-Path $ProjectRoot 'ci\materialize.py')
if($LASTEXITCODE -ne 0){throw "materialize failed rc=$LASTEXITCODE"}

Write-Host '=== FUNCTION DEFINITIONS / REFERENCES ==='
$needles=@('Resolve-MLLMLlamaRuntime','Get-MLLMState','Find-MLLMPython','Snapshot refreshed','SNAPSHOT WARN')
foreach($needle in $needles){
    Write-Host "--- $needle ---"
    Get-ChildItem -LiteralPath $ProjectRoot -Recurse -Include *.ps1,*.psm1 -File |
        Select-String -SimpleMatch $needle |
        ForEach-Object { Write-Host (($_.Path.Substring($ProjectRoot.Length+1))+':'+$_.LineNumber+': '+$_.Line.Trim()) }
}

Write-Host '=== MODULE EXPORT SURFACE ==='
foreach($name in @('Core','State','Detection','Network','Download','Security','Evidence','Runtime')){
    $path=Join-Path $ProjectRoot ('engine\'+$name+'.psm1')
    Import-Module $path -Force -ErrorAction Stop
    $m=Get-Module $name
    $exports=@($m.ExportedCommands.Keys | Sort-Object)
    Write-Host ("MODULE $name exports="+($exports -join ','))
}

Write-Host '=== COMMAND VISIBILITY AFTER MODULE IMPORT ==='
foreach($cmd in @('Resolve-MLLMLlamaRuntime','Get-MLLMState','Find-MLLMPython')){
    $g=Get-Command $cmd -ErrorAction SilentlyContinue
    if($g){Write-Host "VISIBLE $cmd type=$($g.CommandType) source=$($g.Source)"}else{Write-Host "MISSING $cmd"}
}

Write-Host 'DASHBOARD_DIAGNOSTICS=PASS'
