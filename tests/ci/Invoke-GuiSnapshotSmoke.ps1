[CmdletBinding()]
param()
$ErrorActionPreference='Stop'
$ProjectRoot=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path

# Materialize exactly as the raw checkout GUI path does.
& (Join-Path $ProjectRoot 'Bootstrap_SafeCore.ps1') -ProjectRoot $ProjectRoot | Out-Host
if($LASTEXITCODE -ne 0 -and $LASTEXITCODE -ne $null){throw "Bootstrap failed rc=$LASTEXITCODE"}

$dataRoot=Join-Path $env:RUNNER_TEMP 'mllm-gui-snapshot-smoke'
if(Test-Path -LiteralPath $dataRoot){Remove-Item -LiteralPath $dataRoot -Recurse -Force}
New-Item -ItemType Directory -Force -Path $dataRoot | Out-Null

# Important: import ONLY GuiAdapter. Importing engine modules globally here would hide
# the production GUI module-scope bug this test is meant to catch.
Import-Module (Join-Path $ProjectRoot 'gui\GuiAdapter.psm1') -Force -ErrorAction Stop
$s=Get-MLLMGuiSnapshot -ProjectRoot $ProjectRoot -DataRoot $dataRoot -NetworkMode OFFLINE_CACHE

if($null -eq $s){throw 'GUI snapshot returned null'}
$errors=@($s.snapshot_errors)
$commandErrors=@($errors | Where-Object { ([string]$_.error) -match 'CommandNotFoundException|not recognized as the name of a cmdlet|无法将.+识别为' })
if($commandErrors.Count -gt 0){
    $detail=($commandErrors | ForEach-Object { "[$($_.scope):$($_.id)] $($_.error)" }) -join "`n---`n"
    throw "GUI snapshot leaked module scope and lost required commands:`n$detail"
}
foreach($requiredId in @('llama-cpp','local-api','modelscope','python','qwen35-4b','web-workbench')){
    $row=@($s.tasks | Where-Object { $_.id -eq $requiredId }) | Select-Object -First 1
    if($null -eq $row){throw "GUI snapshot missing task row: $requiredId"}
    if(([string]$row.summary) -match 'CommandNotFoundException|not recognized as the name of a cmdlet|无法将.+识别为'){
        throw "GUI task $requiredId contains command visibility failure: $($row.summary)"
    }
}
Write-Host "GUI_SNAPSHOT_SMOKE=PASS tasks=$(@($s.tasks).Count) snapshot_errors=$($errors.Count)"
