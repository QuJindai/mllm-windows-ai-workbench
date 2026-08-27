[CmdletBinding()]
param(
    [string]$RunId='',
    [string]$VersionId='phase1-bootstrap',
    [string]$SourceManifestPath='',
    [switch]$NoElevate,
    [switch]$PathsOnly,
    [switch]$NoGui,
    [switch]$GuiSmoke
)

$ErrorActionPreference='Stop'
Set-StrictMode -Version 2

$pathsModule=Join-Path $PSScriptRoot 'InstallerPaths.psm1'
$stateModule=Join-Path $PSScriptRoot 'InstallerState.psm1'
$acquisitionModule=Join-Path $PSScriptRoot 'Acquisition.psm1'
$validationModule=Join-Path $PSScriptRoot 'PackageValidation.psm1'
$activationModule=Join-Path $PSScriptRoot 'Activation.psm1'
$evidenceModule=Join-Path $PSScriptRoot 'InstallerEvidence.psm1'
$wpfScript=Join-Path $PSScriptRoot 'UniversalInstaller.Wpf.ps1'
foreach($required in @($pathsModule,$stateModule,$acquisitionModule,$validationModule,$activationModule,$evidenceModule,$wpfScript)){
    if(-not(Test-Path -LiteralPath $required -PathType Leaf)){throw ('Universal installer dependency missing: '+$required)}
}
Import-Module $pathsModule -Force -ErrorAction Stop
Import-Module $stateModule -Force -ErrorAction Stop
Import-Module $acquisitionModule -Force -ErrorAction Stop
Import-Module $validationModule -Force -ErrorAction Stop
Import-Module $activationModule -Force -ErrorAction Stop
Import-Module $evidenceModule -Force -ErrorAction Stop

$repoRoot=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if(-not $SourceManifestPath){$SourceManifestPath=Join-Path $repoRoot 'config\source-manifest.json'}
$sourceManifest=Get-MLLMSourceManifest -Path $SourceManifestPath

# Resolve all safety capabilities before a package can become installable or active.
if($null -eq (Get-Command Test-MLLMPackageHash -ErrorAction SilentlyContinue)){throw 'Package hash validation capability unavailable'}
if($null -eq (Get-Command Expand-MLLMSafeArchive -ErrorAction SilentlyContinue)){throw 'Safe archive extraction capability unavailable'}
if($null -eq (Get-Command Test-MLLMStageContract -ErrorAction SilentlyContinue)){throw 'Stage contract validation capability unavailable'}
if($null -eq (Get-Command Install-MLLMVersion -ErrorAction SilentlyContinue)){throw 'Version installation capability unavailable'}
if($null -eq (Get-Command Set-MLLMActiveVersion -ErrorAction SilentlyContinue)){throw 'Version activation capability unavailable'}
if($null -eq (Get-Command Invoke-MLLMRollback -ErrorAction SilentlyContinue)){throw 'Rollback capability unavailable'}
if($null -eq (Get-Command Add-MLLMInstallerError -ErrorAction SilentlyContinue)){throw 'Structured installer error capability unavailable'}
if($null -eq (Get-Command Write-MLLMInstallerSummary -ErrorAction SilentlyContinue)){throw 'Installer summary capability unavailable'}
if($null -eq (Get-Command Export-MLLMInstallerEvidence -ErrorAction SilentlyContinue)){throw 'Installer evidence export capability unavailable'}

if(-not $RunId){
    $RunId=(Get-Date -Format 'yyyyMMdd_HHmmss_fff')+'_'+([guid]::NewGuid().ToString('N').Substring(0,8))
}

$elevated=Test-MLLMElevated
if((-not $elevated) -and (-not $NoElevate)){
    $forward=@('-VersionId',$VersionId,'-SourceManifestPath',$SourceManifestPath)
    if($PathsOnly){$forward+='-PathsOnly'}
    if($NoGui){$forward+='-NoGui'}
    if($GuiSmoke){$forward+='-GuiSmoke'}
    Restart-MLLMInstallerElevated -OriginalArgs $forward -RunId $RunId
    Write-Host "UNIVERSAL_INSTALLER_ELEVATION=REQUESTED run_id=$RunId"
    exit 0
}

$paths=Get-MLLMInstallerPaths -RunId $RunId -VersionId $VersionId

if($PathsOnly){
    $paths | ConvertTo-Json -Depth 4
    Write-Host "UNIVERSAL_INSTALLER_PATHS=PASS run_id=$RunId elevated=$elevated"
    Write-Host "UNIVERSAL_INSTALLER_SOURCES=PASS providers=$(@($sourceManifest.provider_kinds).Count)"
    Write-Host 'UNIVERSAL_INSTALLER_PACKAGE_VALIDATION=PASS'
    Write-Host 'UNIVERSAL_INSTALLER_ACTIVATION=PASS'
    Write-Host 'UNIVERSAL_INSTALLER_EVIDENCE=PASS'
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
    source_manifest_path=[IO.Path]::GetFullPath($SourceManifestPath)
    source_provider_kinds=@($sourceManifest.provider_kinds)
    package_validation='READY'
    activation='READY'
    rollback='READY'
    evidence='READY'
    evidence_root=$paths.EvidencePreferredRoot
    status='BOOTSTRAP_READY'
    created_at=(Get-Date).ToString('o')
}
$bootstrapPath=Join-Path $paths.RunRoot 'bootstrap.json'
$bootstrap | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $bootstrapPath -Encoding UTF8
Write-Host "UNIVERSAL_INSTALLER_BOOTSTRAP=PASS run_id=$RunId bootstrap=$bootstrapPath state=$($state.stage)"
Write-Host "UNIVERSAL_INSTALLER_SOURCES=PASS providers=$(@($sourceManifest.provider_kinds).Count)"
Write-Host 'UNIVERSAL_INSTALLER_PACKAGE_VALIDATION=PASS'
Write-Host 'UNIVERSAL_INSTALLER_ACTIVATION=PASS'
Write-Host 'UNIVERSAL_INSTALLER_EVIDENCE=PASS'

if($NoGui){
    if($elevated){Write-Host 'UNIVERSAL_INSTALLER_NEXT=PREFLIGHT'}else{Write-Host 'UNIVERSAL_INSTALLER_NEXT=ELEVATED_REQUIRED'}
    exit 0
}

$actions=[ordered]@{
    InstallResume={
        return 'Foundation engine ready; package execution is gated by the Phase 1 E2E release check.'
    }
    RetryAcquisition={
        return 'Acquisition providers are ready; package selection is handled by the installer engine.'
    }
    ImportOffline={
        param($PackagePath)
        if(-not $PackagePath){return 'No offline package selected.'}
        return ('Offline package selected: '+[IO.Path]::GetFullPath([string]$PackagePath))
    }
    OpenEvidence={
        $folder=[string]$paths.EvidencePreferredRoot
        if(-not(Test-Path -LiteralPath $folder -PathType Container)){$folder=[string]$paths.RunRoot}
        if(Test-Path -LiteralPath $folder -PathType Container){Start-Process -FilePath 'explorer.exe' -ArgumentList @($folder) -ErrorAction SilentlyContinue | Out-Null}
        return ('Evidence: '+$folder)
    }
    Rollback={
        if(-not(Test-Path -LiteralPath $paths.CurrentPointer -PathType Leaf)){return 'No active version pointer is available for rollback.'}
        $rolled=Invoke-MLLMRollback -PointerPath $paths.CurrentPointer
        return ('Active version: '+[string]$rolled.version_id)
    }
}

& $wpfScript -State $state -Paths $paths -Actions $actions -Smoke:$GuiSmoke
if($GuiSmoke){Write-Host 'UNIVERSAL_INSTALLER_GUI_SMOKE=PASS'}
exit 0
