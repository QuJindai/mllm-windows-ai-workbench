Set-StrictMode -Version 2
$ErrorActionPreference='Stop'

$script:MLLMInstallerStageSequence=@(
    'INIT',
    'ELEVATED',
    'PREFLIGHT',
    'ACQUIRE',
    'VERIFY_PACKAGE',
    'EXTRACT',
    'VALIDATE_STAGE',
    'INSTALL_VERSION',
    'VERIFY_INSTALL',
    'ACTIVATE',
    'COMPLETE'
)

function New-MLLMInstallerState {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)][ValidateNotNullOrEmpty()][string]$RunId,
        [Parameter(Mandatory=$true)][ValidateNotNullOrEmpty()][string]$VersionId,
        [Parameter(Mandatory=$true)]$Paths
    )

    [ordered]@{
        schema='mllm.universal-installer.state.v1'
        run_id=$RunId
        version_id=$VersionId
        stage='INIT'
        stage_sequence=@($script:MLLMInstallerStageSequence)
        completed_stages=@('INIT')
        source_attempts=@()
        selected_source=$null
        package_sha256=$null
        staging_path=[string]$Paths.StagingRoot
        installed_version_path=$null
        previous_active_version=$null
        new_active_version=$null
        errors=@()
        updated_at=(Get-Date).ToString('o')
    }
}

function Save-MLLMInstallerState {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)]$State,
        [Parameter(Mandatory=$true)][ValidateNotNullOrEmpty()][string]$Path
    )

    $full=[IO.Path]::GetFullPath($Path)
    $dir=Split-Path -Parent $full
    if(-not(Test-Path -LiteralPath $dir -PathType Container)){
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
    }

    $State.updated_at=(Get-Date).ToString('o')
    $json=$State | ConvertTo-Json -Depth 20
    $tmp=$full+'.tmp'
    $backup=$full+'.bak'
    $utf8=New-Object Text.UTF8Encoding($false)
    [IO.File]::WriteAllText($tmp,$json,$utf8)

    try{
        if(Test-Path -LiteralPath $full -PathType Leaf){
            if(Test-Path -LiteralPath $backup -PathType Leaf){Remove-Item -LiteralPath $backup -Force}
            [IO.File]::Replace($tmp,$full,$backup,$true)
            if(Test-Path -LiteralPath $backup -PathType Leaf){Remove-Item -LiteralPath $backup -Force}
        }else{
            Move-Item -LiteralPath $tmp -Destination $full -Force
        }
    }catch{
        if(Test-Path -LiteralPath $tmp -PathType Leaf){Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue}
        if(Test-Path -LiteralPath $backup -PathType Leaf){Remove-Item -LiteralPath $backup -Force -ErrorAction SilentlyContinue}
        throw
    }
    return $full
}

function Read-MLLMInstallerState {
    [CmdletBinding()]
    param([Parameter(Mandatory=$true)][ValidateNotNullOrEmpty()][string]$Path)

    if(-not(Test-Path -LiteralPath $Path -PathType Leaf)){return $null}
    $raw=Get-Content -LiteralPath $Path -Raw -Encoding UTF8
    if(-not $raw){throw "Installer state is empty: $Path"}
    $state=$raw | ConvertFrom-Json
    if([string]$state.schema -ne 'mllm.universal-installer.state.v1'){
        throw "Unsupported installer state schema: $($state.schema)"
    }
    return $state
}

function Test-MLLMStageComplete {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)]$State,
        [Parameter(Mandatory=$true)][ValidateNotNullOrEmpty()][string]$Stage
    )
    return (@($State.completed_stages) -contains $Stage)
}

function Set-MLLMInstallerStage {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)]$State,
        [Parameter(Mandatory=$true)][ValidateNotNullOrEmpty()][string]$Stage,
        [Parameter(Mandatory=$true)][ValidateNotNullOrEmpty()][string]$StatePath
    )

    $target=[Array]::IndexOf([string[]]$script:MLLMInstallerStageSequence,$Stage)
    if($target -lt 0){throw "Unknown installer stage: $Stage"}
    $current=[Array]::IndexOf([string[]]$script:MLLMInstallerStageSequence,[string]$State.stage)
    if($current -lt 0){throw "Current installer stage is invalid: $($State.stage)"}
    if($target -gt ($current+1)){
        throw "Installer stage cannot skip from $($State.stage) to $Stage"
    }

    $State.stage=$Stage
    if(-not(@($State.completed_stages) -contains $Stage)){
        $State.completed_stages=@($State.completed_stages)+@($Stage)
    }
    Save-MLLMInstallerState -State $State -Path $StatePath | Out-Null
    return $State
}

Export-ModuleMember -Function New-MLLMInstallerState,Save-MLLMInstallerState,Read-MLLMInstallerState,Set-MLLMInstallerStage,Test-MLLMStageComplete
