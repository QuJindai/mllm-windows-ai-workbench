Set-StrictMode -Version 2
$ErrorActionPreference='Stop'

foreach($moduleName in @('InstallerState.psm1','Acquisition.psm1','PackageValidation.psm1','Activation.psm1','InstallerEvidence.psm1')){
    $modulePath=Join-Path $PSScriptRoot $moduleName
    if(-not(Test-Path -LiteralPath $modulePath -PathType Leaf)){throw ('Installer engine dependency missing: '+$modulePath)}
    Import-Module $modulePath -ErrorAction Stop
}

function Get-MLLMEngineValue {
    param($Object,[Parameter(Mandatory=$true)][string]$Name,$Default=$null)
    if($null -eq $Object){return $Default}
    if($Object -is [Collections.IDictionary]){
        if($Object.Contains($Name)){return $Object[$Name]}
        return $Default
    }
    $prop=$Object.PSObject.Properties[$Name]
    if($null -ne $prop){return $prop.Value}
    return $Default
}

function Get-MLLMPackageCachePath {
    param(
        [Parameter(Mandatory=$true)]$Package,
        [Parameter(Mandatory=$true)][string]$CacheRoot
    )
    $fileName=[string](Get-MLLMEngineValue -Object $Package -Name 'file_name' -Default '')
    if(-not $fileName){$fileName=([string]$Package.id)+'-'+([string]$Package.version)+'.pkg'}
    return Join-Path ([IO.Path]::GetFullPath($CacheRoot)) (([string]$Package.id)+'\'+([string]$Package.version)+'\'+$fileName)
}

function Test-MLLMEngineStop {
    param([string]$StopAfterStage,[string]$Stage)
    return ((-not [string]::IsNullOrWhiteSpace($StopAfterStage)) -and ($StopAfterStage -eq $Stage))
}

function New-MLLMEngineResult {
    param(
        [string]$Status,
        [string]$Stage,
        $State,
        [string]$Evidence='',
        [string]$Error='',
        [string]$FailedStage=''
    )
    return [pscustomobject]@{
        status=$Status
        stage=$Stage
        state=$State
        evidence=$Evidence
        error=$Error
        failed_stage=$FailedStage
    }
}

function Invoke-MLLMFoundationInstall {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)]$Package,
        [Parameter(Mandatory=$true)]$Paths,
        [Parameter(Mandatory=$true)]$State,
        [Parameter(Mandatory=$true)][ValidateNotNullOrEmpty()][string]$StatePath,
        [Parameter(Mandatory=$true)][ValidateNotNullOrEmpty()][string]$PreferredEvidenceRoot,
        [string]$StopAfterStage=''
    )

    $failStage=[string](Get-MLLMEngineValue -Object $State -Name 'stage' -Default 'INIT')
    $acquiredPath=Get-MLLMPackageCachePath -Package $Package -CacheRoot ([string]$Paths.CacheRoot)
    $stagePayload=Join-Path ([string]$Paths.StagingRoot) 'payload'
    $installedPath=[string](Get-MLLMEngineValue -Object $State -Name 'installed_version_path' -Default '')

    try{
        foreach($dir in @($Paths.CacheRoot,$Paths.StagingRoot,$Paths.RunRoot,(Split-Path -Parent $StatePath),(Split-Path -Parent $Paths.CurrentPointer),(Split-Path -Parent $Paths.InstallVersionRoot))){
            if(-not(Test-Path -LiteralPath $dir -PathType Container)){New-Item -ItemType Directory -Force -Path $dir | Out-Null}
        }

        $failStage='ELEVATED'
        if(-not(Test-MLLMStageComplete -State $State -Stage 'ELEVATED')){
            Set-MLLMInstallerStage -State $State -Stage 'ELEVATED' -StatePath $StatePath | Out-Null
        }
        if(Test-MLLMEngineStop -StopAfterStage $StopAfterStage -Stage 'ELEVATED'){
            return New-MLLMEngineResult -Status 'INTERRUPTED' -Stage 'ELEVATED' -State $State
        }

        $failStage='PREFLIGHT'
        if(-not(Test-MLLMStageComplete -State $State -Stage 'PREFLIGHT')){
            $expected=[string](Get-MLLMEngineValue -Object $Package -Name 'sha256' -Default '')
            if($expected -notmatch '^[0-9A-Fa-f]{64}$'){throw 'Package SHA256 contract is invalid'}
            if(@(Get-MLLMEngineValue -Object $Package -Name 'sources' -Default @()).Count -lt 1){throw 'Package source list is empty'}
            Set-MLLMInstallerStage -State $State -Stage 'PREFLIGHT' -StatePath $StatePath | Out-Null
        }
        if(Test-MLLMEngineStop -StopAfterStage $StopAfterStage -Stage 'PREFLIGHT'){
            return New-MLLMEngineResult -Status 'INTERRUPTED' -Stage 'PREFLIGHT' -State $State
        }

        $failStage='ACQUIRE'
        if(-not(Test-MLLMStageComplete -State $State -Stage 'ACQUIRE')){
            $acquired=Invoke-MLLMAcquirePackage -Package $Package -CacheRoot ([string]$Paths.CacheRoot) -State $State -StatePath $StatePath
            $acquiredPath=[string]$acquired.path
            Set-MLLMInstallerStage -State $State -Stage 'ACQUIRE' -StatePath $StatePath | Out-Null
        }elseif(-not(Test-Path -LiteralPath $acquiredPath -PathType Leaf)){
            throw ('Acquisition checkpoint exists but cached package is missing: '+$acquiredPath)
        }
        if(Test-MLLMEngineStop -StopAfterStage $StopAfterStage -Stage 'ACQUIRE'){
            return New-MLLMEngineResult -Status 'INTERRUPTED' -Stage 'ACQUIRE' -State $State
        }

        $failStage='VERIFY_PACKAGE'
        if(-not(Test-MLLMStageComplete -State $State -Stage 'VERIFY_PACKAGE')){
            if(-not (Test-MLLMPackageHash -Path $acquiredPath -ExpectedSha256 ([string]$Package.sha256))){throw 'Cached package SHA256 verification failed'}
            Set-MLLMInstallerStage -State $State -Stage 'VERIFY_PACKAGE' -StatePath $StatePath | Out-Null
        }
        if(Test-MLLMEngineStop -StopAfterStage $StopAfterStage -Stage 'VERIFY_PACKAGE'){
            return New-MLLMEngineResult -Status 'INTERRUPTED' -Stage 'VERIFY_PACKAGE' -State $State
        }

        $failStage='EXTRACT'
        if(-not(Test-MLLMStageComplete -State $State -Stage 'EXTRACT')){
            if(Test-Path -LiteralPath $stagePayload -PathType Container){Remove-Item -LiteralPath $stagePayload -Recurse -Force}
            New-Item -ItemType Directory -Force -Path $stagePayload | Out-Null
            Expand-MLLMSafeArchive -ArchivePath $acquiredPath -Destination $stagePayload | Out-Null
            Set-MLLMInstallerStage -State $State -Stage 'EXTRACT' -StatePath $StatePath | Out-Null
        }elseif(-not(Test-Path -LiteralPath $stagePayload -PathType Container)){
            throw ('Extract checkpoint exists but staged payload is missing: '+$stagePayload)
        }
        if(Test-MLLMEngineStop -StopAfterStage $StopAfterStage -Stage 'EXTRACT'){
            return New-MLLMEngineResult -Status 'INTERRUPTED' -Stage 'EXTRACT' -State $State
        }

        $failStage='VALIDATE_STAGE'
        if(-not(Test-MLLMStageComplete -State $State -Stage 'VALIDATE_STAGE')){
            $contract=Test-MLLMStageContract -StageRoot $stagePayload
            if([string]$contract.status -ne 'PASS'){throw ('Stage contract failed: '+(@($contract.errors) -join ' | '))}
            Set-MLLMInstallerStage -State $State -Stage 'VALIDATE_STAGE' -StatePath $StatePath | Out-Null
        }
        if(Test-MLLMEngineStop -StopAfterStage $StopAfterStage -Stage 'VALIDATE_STAGE'){
            return New-MLLMEngineResult -Status 'INTERRUPTED' -Stage 'VALIDATE_STAGE' -State $State
        }

        $failStage='INSTALL_VERSION'
        if(-not(Test-MLLMStageComplete -State $State -Stage 'INSTALL_VERSION')){
            $installed=Install-MLLMVersion -StageRoot $stagePayload -VersionRoot ([string]$Paths.InstallVersionRoot)
            $installedPath=[string]$installed.version_path
            $State.installed_version_path=$installedPath
            Save-MLLMInstallerState -State $State -Path $StatePath | Out-Null
            Set-MLLMInstallerStage -State $State -Stage 'INSTALL_VERSION' -StatePath $StatePath | Out-Null
        }else{
            $installedPath=[string](Get-MLLMEngineValue -Object $State -Name 'installed_version_path' -Default '')
            if(-not $installedPath){$installedPath=[string]$Paths.InstallVersionRoot}
        }
        if(Test-MLLMEngineStop -StopAfterStage $StopAfterStage -Stage 'INSTALL_VERSION'){
            return New-MLLMEngineResult -Status 'INTERRUPTED' -Stage 'INSTALL_VERSION' -State $State
        }

        $failStage='VERIFY_INSTALL'
        if(-not(Test-MLLMStageComplete -State $State -Stage 'VERIFY_INSTALL')){
            $installedCheck=Test-MLLMInstalledVersion -VersionRoot $installedPath
            if([string]$installedCheck.status -ne 'PASS'){throw ('Installed version verification failed: '+(@($installedCheck.errors) -join ' | '))}
            Set-MLLMInstallerStage -State $State -Stage 'VERIFY_INSTALL' -StatePath $StatePath | Out-Null
        }
        if(Test-MLLMEngineStop -StopAfterStage $StopAfterStage -Stage 'VERIFY_INSTALL'){
            return New-MLLMEngineResult -Status 'INTERRUPTED' -Stage 'VERIFY_INSTALL' -State $State
        }

        $failStage='ACTIVATE'
        if(-not(Test-MLLMStageComplete -State $State -Stage 'ACTIVATE')){
            $previous=$null
            if(Test-Path -LiteralPath $Paths.CurrentPointer -PathType Leaf){$previous=Get-MLLMActiveVersion -PointerPath ([string]$Paths.CurrentPointer)}
            $State.previous_active_version=$previous
            Save-MLLMInstallerState -State $State -Path $StatePath | Out-Null
            $active=Set-MLLMActiveVersion -PointerPath ([string]$Paths.CurrentPointer) -VersionId ([string]$State.version_id) -VersionPath $installedPath -Previous $previous
            $State.new_active_version=$active
            Save-MLLMInstallerState -State $State -Path $StatePath | Out-Null
            Set-MLLMInstallerStage -State $State -Stage 'ACTIVATE' -StatePath $StatePath | Out-Null
        }
        if(Test-MLLMEngineStop -StopAfterStage $StopAfterStage -Stage 'ACTIVATE'){
            return New-MLLMEngineResult -Status 'INTERRUPTED' -Stage 'ACTIVATE' -State $State
        }

        $failStage='COMPLETE'
        if(-not(Test-MLLMStageComplete -State $State -Stage 'COMPLETE')){
            Set-MLLMInstallerStage -State $State -Stage 'COMPLETE' -StatePath $StatePath | Out-Null
        }
        $evidence=Export-MLLMInstallerEvidence -State $State -RunRoot ([string]$Paths.RunRoot) -PreferredEvidenceRoot $PreferredEvidenceRoot
        return New-MLLMEngineResult -Status 'PASS' -Stage 'COMPLETE' -State $State -Evidence $evidence
    }catch{
        $message=$_.Exception.Message
        try{
            Add-MLLMInstallerError -State $State -Stage $failStage -Exception $_.Exception -Context @{core_install_authorized=$false;package_id=[string]$Package.id;version_id=[string]$State.version_id} -StatePath $StatePath | Out-Null
        }catch{}
        $evidence=''
        try{$evidence=Export-MLLMInstallerEvidence -State $State -RunRoot ([string]$Paths.RunRoot) -PreferredEvidenceRoot $PreferredEvidenceRoot}catch{}
        return New-MLLMEngineResult -Status 'FAIL' -Stage ([string]$State.stage) -State $State -Evidence $evidence -Error $message -FailedStage $failStage
    }
}

Export-ModuleMember -Function Invoke-MLLMFoundationInstall
