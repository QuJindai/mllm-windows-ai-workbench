[CmdletBinding()]
param()
$ErrorActionPreference='Stop'
Set-StrictMode -Version 2

$Root=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$activation=Join-Path $Root 'installer\Activation.psm1'
if(-not(Test-Path -LiteralPath $activation -PathType Leaf)){throw "Activation.psm1 missing: $activation"}
Import-Module $activation -Force -ErrorAction Stop

$temp=Join-Path $env:RUNNER_TEMP ('mllm-activation-'+[guid]::NewGuid().ToString('N'))
$versions=Join-Path $temp 'versions'
$pointer=Join-Path $temp 'state\current.json'
New-Item -ItemType Directory -Force -Path $versions | Out-Null

function New-Stage {
    param([string]$Name,[string]$Marker,[switch]$Invalid)
    $stage=Join-Path $temp $Name
    New-Item -ItemType Directory -Force -Path $stage | Out-Null
    [IO.File]::WriteAllText((Join-Path $stage 'Start_M_LLM_Workbench.ps1'),("[CmdletBinding()]`r`nparam()`r`nWrite-Host '"+$Marker+"'`r`n"),(New-Object Text.UTF8Encoding($false)))
    if(-not $Invalid){
        foreach($f in @('Bootstrap_SafeCore.ps1','M_LLM_PHYSICAL_PREFLIGHT.ps1','M_LLM_GUI_PREFLIGHT.ps1')){
            [IO.File]::WriteAllText((Join-Path $stage $f),("[CmdletBinding()]`r`nparam()`r`nWrite-Host '"+$Marker+"'`r`n"),(New-Object Text.UTF8Encoding($false)))
        }
    }
    New-Item -ItemType Directory -Force -Path (Join-Path $stage 'nested') | Out-Null
    [IO.File]::WriteAllText((Join-Path $stage 'nested\payload.txt'),$Marker,(New-Object Text.UTF8Encoding($false)))
    return $stage
}

$stage1=New-Stage -Name 'stage-v1' -Marker 'V1'
$v1Root=Join-Path $versions 'v1'
$i1=Install-MLLMVersion -StageRoot $stage1 -VersionRoot $v1Root
if([string]$i1.status -ne 'PASS'){throw "v1 install failed: $($i1.status)"}
$check1=Test-MLLMInstalledVersion -VersionRoot $i1.version_path
if([string]$check1.status -ne 'PASS'){throw 'v1 installed version did not verify'}
$p1=Set-MLLMActiveVersion -PointerPath $pointer -VersionId 'v1' -VersionPath $i1.version_path -Previous $null
if([string]$p1.version_id -ne 'v1'){throw 'v1 pointer activation failed'}

$lockPath=Join-Path $i1.version_path 'Start_M_LLM_Workbench.ps1'
$lock=[IO.File]::Open($lockPath,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
try{
    $stage2=New-Stage -Name 'stage-v2' -Marker 'V2'
    $v2Root=Join-Path $versions 'v2'
    $i2=Install-MLLMVersion -StageRoot $stage2 -VersionRoot $v2Root
    if([string]$i2.status -ne 'PASS'){throw "v2 install failed: $($i2.status)"}
    $activeBefore=Get-MLLMActiveVersion -PointerPath $pointer
    $p2=Set-MLLMActiveVersion -PointerPath $pointer -VersionId 'v2' -VersionPath $i2.version_path -Previous $activeBefore
    if([string]$p2.version_id -ne 'v2'){throw 'v2 pointer activation failed'}
    if(-not(Test-Path -LiteralPath $lockPath -PathType Leaf)){throw 'locked v1 file was touched or removed'}
    if((Get-Content -LiteralPath (Join-Path $i1.version_path 'nested\payload.txt') -Raw) -ne 'V1'){throw 'v1 content changed while installing v2'}
    Write-Host 'VERSION_ACTIVATION_SMOKE=PASS old_version_locked=true active=v2'

    $bad=New-Stage -Name 'stage-v3-invalid' -Marker 'V3' -Invalid
    $badCheck=Test-MLLMInstalledVersion -VersionRoot $bad
    if([string]$badCheck.status -ne 'FAIL'){throw 'invalid v3 stage was accepted'}
    $rejected=$false
    try{Set-MLLMActiveVersion -PointerPath $pointer -VersionId 'v3' -VersionPath $bad -Previous $p2 | Out-Null}catch{$rejected=$true}
    if(-not $rejected){throw 'invalid v3 activation was not rejected'}
    $still=Get-MLLMActiveVersion -PointerPath $pointer
    if([string]$still.version_id -ne 'v2'){throw "invalid v3 changed current pointer to $($still.version_id)"}
    Write-Host 'FAILED_VERSION_PRESERVES_ACTIVE=PASS active=v2'

    $rolled=Invoke-MLLMRollback -PointerPath $pointer
    if([string]$rolled.version_id -ne 'v1'){throw "rollback did not restore v1: $($rolled.version_id)"}
    if(-not(Test-Path -LiteralPath $i2.version_path -PathType Container)){throw 'rollback deleted v2 instead of only switching pointer'}
    Write-Host 'ROLLBACK_SMOKE=PASS active=v1'
}finally{
    $lock.Dispose()
}

if(Test-Path -LiteralPath ($pointer+'.tmp') -PathType Leaf){throw 'activation pointer temp file leaked'}
