[CmdletBinding()]
param(
    [string]$RunId='',
    [string]$VersionId='phase1-bootstrap',
    [switch]$NoElevate,
    [switch]$PathsOnly
)

$ErrorActionPreference='Stop'
Set-StrictMode -Version 2

$pathsModule=Join-Path $PSScriptRoot 'InstallerPaths.psm1'
$stateModule=Join-Path $PSScriptRoot 'InstallerState.psm1'
if(-not(Test-Path -LiteralPath $pathsModule -PathType Leaf)){throw 'InstallerPaths.psm1 missing'}
if(-not(Test-Path -LiteralPath $stateModule -PathType Leaf)){throw 'InstallerState.psm1 missing'}
Import-Module $pathsModule -Force -ErrorAction Stop
Import-Module $stateModule -Force -ErrorAction Stop

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

$state=Read-MLLMInstallerState -Path $paths.StatePath
if(($null -eq $state) -or ([string]$state.run_id -ne $RunId) -or ([string]$state.version_id -ne $VersionId)){
    $state=New-MLLMInstallerState -RunId $RunId -VersionId $VersionId -Paths $paths
    Save-MLLMInstallerState -State $state -Path $paths.StatePath | Out-Null
    Write-Host "UNIVERSAL_INSTALLER_STATE=NEW run_id=$RunId stage=$($state.stage)"
}else{
    Write-Host "UNIVERSAL_INSTALLER_STATE=RESUME run_id=$RunId stage=$($state.stage)"
}

if($elevated -and (-not(Test-MLLMStageComplete -State $state -Stage 'ELEVATED'))){
    Set-MLLMInstallerStage -State $state -Stage 'ELEVATED' -StatePath $paths.StatePath | Out-Null
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
    state_path=$paths.StatePath
    state_stage=[string]$state.stage
    evidence_root=$paths.EvidencePreferredRoot
    status='BOOTSTRAP_READY'
    created_at=(Get-Date).ToString('o')
}
$bootstrapPath=Join-Path $paths.RunRoot 'bootstrap.json'
$bootstrap | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $bootstrapPath -Encoding UTF8
Write-Host "UNIVERSAL_INSTALLER_BOOTSTRAP=PASS run_id=$RunId bootstrap=$bootstrapPath state=$($state.stage)"
if($elevated){
    Write-Host 'UNIVERSAL_INSTALLER_NEXT=PREFLIGHT'
}else{
    Write-Host 'UNIVERSAL_INSTALLER_NEXT=ELEVATED_REQUIRED'
}
exit 0
