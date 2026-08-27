Set-StrictMode -Version 2
$ErrorActionPreference='Stop'

function Test-MLLMElevated {
    [CmdletBinding()]
    param()
    $identity=[Security.Principal.WindowsIdentity]::GetCurrent()
    $principal=New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-MLLMInstallerPaths {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)][ValidateNotNullOrEmpty()][string]$RunId,
        [Parameter(Mandatory=$true)][ValidateNotNullOrEmpty()][string]$VersionId
    )

    if(-not $env:ProgramFiles){throw 'ProgramFiles environment variable is unavailable'}
    if(-not $env:ProgramData){throw 'ProgramData environment variable is unavailable'}
    if(-not $env:USERPROFILE){throw 'USERPROFILE environment variable is unavailable'}

    $programRoot=Join-Path $env:ProgramFiles 'M-LLM\Workbench'
    $programDataRoot=Join-Path $env:ProgramData 'M-LLM'
    [pscustomobject]@{
        ProgramRoot=$programRoot
        VersionsRoot=(Join-Path $programRoot 'versions')
        InstallVersionRoot=(Join-Path $programRoot ('versions\'+$VersionId))
        ProgramDataRoot=$programDataRoot
        CacheRoot=(Join-Path $programDataRoot 'Installer\cache')
        StagingRoot=(Join-Path $programDataRoot ('Installer\staging\'+$RunId))
        RunRoot=(Join-Path $programDataRoot ('Installer\runs\'+$RunId))
        StatePath=(Join-Path $programDataRoot 'Installer\state\installer_state.json')
        CurrentPointer=(Join-Path $programDataRoot 'Workbench\current.json')
        SharedDataRoot=(Join-Path $programDataRoot 'Data')
        EvidencePreferredRoot=(Join-Path $env:USERPROFILE ('Downloads\M_LLM_EVIDENCE\'+$RunId))
    }
}

function New-MLLMElevationArguments {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)][ValidateNotNullOrEmpty()][string]$EntryPath,
        [Parameter(Mandatory=$true)][ValidateNotNullOrEmpty()][string]$RunId,
        [string[]]$OriginalArgs=@()
    )

    $payloadObject=[ordered]@{
        entry=[IO.Path]::GetFullPath($EntryPath)
        run_id=$RunId
        args=@($OriginalArgs | ForEach-Object {[string]$_})
    }
    $json=$payloadObject | ConvertTo-Json -Depth 6 -Compress
    $payload=[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($json))
    $script=@'
$payload='__PAYLOAD__'
$json=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($payload))
$o=$json | ConvertFrom-Json
$forward=@('-RunId',[string]$o.run_id)+@($o.args | ForEach-Object {[string]$_})
& ([string]$o.entry) @forward
exit $LASTEXITCODE
'@
    $script=$script.Replace('__PAYLOAD__',$payload)
    $encoded=[Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($script))
    return [pscustomobject]@{
        ArgumentList=@('-NoProfile','-ExecutionPolicy','Bypass','-EncodedCommand',$encoded)
        PayloadJson=$json
    }
}

function Restart-MLLMInstallerElevated {
    [CmdletBinding()]
    param(
        [string[]]$OriginalArgs=@(),
        [Parameter(Mandatory=$true)][ValidateNotNullOrEmpty()][string]$RunId
    )

    $entry=Join-Path $PSScriptRoot 'Start-UniversalInstaller.ps1'
    if(-not(Test-Path -LiteralPath $entry -PathType Leaf)){throw "Universal installer entrypoint missing: $entry"}
    $elevation=New-MLLMElevationArguments -EntryPath $entry -RunId $RunId -OriginalArgs $OriginalArgs
    Start-Process -FilePath 'powershell.exe' -Verb RunAs -ArgumentList @($elevation.ArgumentList)
}

Export-ModuleMember -Function Test-MLLMElevated,Get-MLLMInstallerPaths,New-MLLMElevationArguments,Restart-MLLMInstallerElevated
