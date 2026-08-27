[CmdletBinding()]
param(
    [string]$RunId='',
    [string]$VersionId='phase1-bootstrap',
    [switch]$NoElevate,
    [switch]$PathsOnly
)

$ErrorActionPreference='Stop'
Set-StrictMode -Version 2

$module=Join-Path $PSScriptRoot 'InstallerPaths.psm1'
if(-not(Test-Path -LiteralPath $module -PathType Leaf)){throw 'InstallerPaths.psm1 missing'}
Import-Module $module -Force -ErrorAction Stop

if(-not $RunId){
    $RunId=(Get-Date -Format 'yyyyMMdd_HHmmss_fff')+'_'+([guid]::NewGuid().ToString('N').Substring(0,8))
}

$elevated=Test-MLLMElevated
if((-not $elevated) -and (-not $NoElevate)){
    $forward=@('-VersionId',$VersionId)
    if($PathsOnly){$forward+='-PathsOnly'}
    Restart-MLLMInstallerElevated -OriginalArgs $forward -RunId $RunId
    Write-Host "UNIVERSAL_INSTALLER_ELEVATION=REQUESTED run_id=$RunId"
    exit 0
}

$paths=Get-MLLMInstallerPaths -RunId $RunId -VersionId $VersionId

if($PathsOnly){
    $paths | ConvertTo-Json -Depth 4
    Write-Host "UNIVERSAL_INSTALLER_PATHS=PASS run_id=$RunId elevated=$elevated"
    exit 0
}

if(-not $elevated){
    Write-Host "UNIVERSAL_INSTALLER_MODE=NO_ELEVATE run_id=$RunId"
}else{
    Write-Host "UNIVERSAL_INSTALLER_MODE=ADMIN run_id=$RunId"
}

$dirs=@(
    $paths.ProgramDataRoot,
    $paths.CacheRoot,
    $paths.StagingRoot,
    $paths.RunRoot,
    (Split-Path -Parent $paths.StatePath),
    (Split-Path -Parent $paths.CurrentPointer),
    $paths.SharedDataRoot,
    $paths.EvidencePreferredRoot
)
foreach($dir in $dirs){
    if(-not(Test-Path -LiteralPath $dir -PathType Container)){
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
    }
}

$bootstrap=[ordered]@{
    schema='mllm.universal-installer.bootstrap.v1'
    run_id=$RunId
    version_id=$VersionId
    elevated=$elevated
    program_root=$paths.ProgramRoot
    staging_root=$paths.StagingRoot
    cache_root=$paths.CacheRoot
    run_root=$paths.RunRoot
    evidence_root=$paths.EvidencePreferredRoot
    status='BOOTSTRAP_READY'
    created_at=(Get-Date).ToString('o')
}
$bootstrapPath=Join-Path $paths.RunRoot 'bootstrap.json'
$bootstrap | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $bootstrapPath -Encoding UTF8
Write-Host "UNIVERSAL_INSTALLER_BOOTSTRAP=PASS run_id=$RunId bootstrap=$bootstrapPath"
Write-Host 'UNIVERSAL_INSTALLER_NEXT=STATE_MACHINE'
exit 0
