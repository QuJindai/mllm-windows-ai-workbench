[CmdletBinding()]
param()
$ErrorActionPreference='Stop'
$ProjectRoot=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path

python (Join-Path $ProjectRoot 'ci\materialize.py')
if($LASTEXITCODE -ne 0){throw "materialize failed rc=$LASTEXITCODE"}

Write-Host '=== FUNCTION DEFINITIONS / REFERENCES ==='
$needles=@('Resolve-MLLMLlamaRuntime','Get-MLLMState','Find-MLLMPython','Snapshot refreshed','SNAPSHOT WARN','Get-MLLMGuiSnapshot','Get-MLLMTaskStatus')
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

function Show-FileWithLines([string]$Relative,[int]$From=1,[int]$To=220){
    Write-Host "=== FILE $Relative [$From..$To] ==="
    $p=Join-Path $ProjectRoot $Relative
    $lines=@(Get-Content -LiteralPath $p -Encoding UTF8)
    $last=[Math]::Min($To,$lines.Count)
    for($i=$From;$i -le $last;$i++){ Write-Host (('{0,4}: ' -f $i)+$lines[$i-1]) }
}

Show-FileWithLines 'gui\GuiAdapter.psm1' 1 180
Show-FileWithLines 'gui\Workbench.Wpf.ps1' 1 120
Show-FileWithLines 'engine\Core.psm1' 1 280

Write-Host 'DASHBOARD_DIAGNOSTICS=PASS'
