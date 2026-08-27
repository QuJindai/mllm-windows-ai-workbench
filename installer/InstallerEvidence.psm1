Set-StrictMode -Version 2
$ErrorActionPreference='Stop'

$stateModule=Join-Path $PSScriptRoot 'InstallerState.psm1'
if(-not(Get-Command Save-MLLMInstallerState -ErrorAction SilentlyContinue)){
    if(-not(Test-Path -LiteralPath $stateModule -PathType Leaf)){throw 'InstallerState.psm1 missing'}
    Import-Module $stateModule -Force -ErrorAction Stop
}

function Get-MLLMValue {
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

function Write-MLLMUtf8Json {
    param(
        [Parameter(Mandatory=$true)]$Value,
        [Parameter(Mandatory=$true)][string]$Path,
        [int]$Depth=20
    )
    $full=[IO.Path]::GetFullPath($Path)
    $dir=Split-Path -Parent $full
    if(-not(Test-Path -LiteralPath $dir -PathType Container)){New-Item -ItemType Directory -Force -Path $dir | Out-Null}
    $utf8=New-Object Text.UTF8Encoding($false)
    [IO.File]::WriteAllText($full,($Value | ConvertTo-Json -Depth $Depth),$utf8)
    return $full
}

function Get-MLLMInstallerSystemProfile {
    $os=$null
    try{$os=Get-CimInstance Win32_OperatingSystem -ErrorAction Stop}catch{}
    [ordered]@{
        captured_at=(Get-Date).ToString('o')
        computer_name=[string]$env:COMPUTERNAME
        user_name=[string]$env:USERNAME
        os_caption=if($null -ne $os){[string]$os.Caption}else{[Environment]::OSVersion.VersionString}
        os_version=if($null -ne $os){[string]$os.Version}else{[string][Environment]::OSVersion.Version}
        os_build=if($null -ne $os){[string]$os.BuildNumber}else{[string][Environment]::OSVersion.Version.Build}
        architecture=[string]$env:PROCESSOR_ARCHITECTURE
        ps_version=[string]$PSVersionTable.PSVersion
        culture=[Globalization.CultureInfo]::CurrentCulture.Name
        ansi_code_page=[Text.Encoding]::Default.CodePage
    }
}

function Add-MLLMInstallerError {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)]$State,
        [Parameter(Mandatory=$true)][ValidateNotNullOrEmpty()][string]$Stage,
        [Parameter(Mandatory=$true)][Exception]$Exception,
        $Context=@{},
        [Parameter(Mandatory=$true)][ValidateNotNullOrEmpty()][string]$StatePath
    )

    $entry=[pscustomobject]@{
        stage=$Stage
        type=$Exception.GetType().FullName
        message=$Exception.Message
        context=$Context
        timestamp=(Get-Date).ToString('o')
    }
    $existing=@(Get-MLLMValue -Object $State -Name 'errors' -Default @())
    $State.errors=@($existing)+@($entry)
    Save-MLLMInstallerState -State $State -Path $StatePath | Out-Null
    return $entry
}

function Write-MLLMInstallerSummary {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)]$State,
        [Parameter(Mandatory=$true)][ValidateNotNullOrEmpty()][string]$RunRoot
    )

    $root=[IO.Path]::GetFullPath($RunRoot)
    if(-not(Test-Path -LiteralPath $root -PathType Container)){New-Item -ItemType Directory -Force -Path $root | Out-Null}

    $statePath=Join-Path $root 'installer_state.json'
    Save-MLLMInstallerState -State $State -Path $statePath | Out-Null

    $attempts=@(Get-MLLMValue -Object $State -Name 'source_attempts' -Default @())
    $attemptsPath=Write-MLLMUtf8Json -Value $attempts -Path (Join-Path $root 'source_attempts.json')
    $profile=Get-MLLMInstallerSystemProfile
    $profilePath=Write-MLLMUtf8Json -Value $profile -Path (Join-Path $root 'system_profile.json')

    $logPath=Join-Path $root 'installer.log'
    if(-not(Test-Path -LiteralPath $logPath -PathType Leaf)){
        $utf8=New-Object Text.UTF8Encoding($false)
        [IO.File]::WriteAllText($logPath,'',$utf8)
    }

    $summary=[ordered]@{
        schema='mllm.universal-installer.summary.v1'
        run_id=[string](Get-MLLMValue -Object $State -Name 'run_id' -Default '')
        version_id=[string](Get-MLLMValue -Object $State -Name 'version_id' -Default '')
        stage=[string](Get-MLLMValue -Object $State -Name 'stage' -Default '')
        completed_stages=@(Get-MLLMValue -Object $State -Name 'completed_stages' -Default @())
        selected_source=Get-MLLMValue -Object $State -Name 'selected_source' -Default $null
        package_sha256=Get-MLLMValue -Object $State -Name 'package_sha256' -Default $null
        staging_path=Get-MLLMValue -Object $State -Name 'staging_path' -Default $null
        installed_version_path=Get-MLLMValue -Object $State -Name 'installed_version_path' -Default $null
        previous_active_version=Get-MLLMValue -Object $State -Name 'previous_active_version' -Default $null
        new_active_version=Get-MLLMValue -Object $State -Name 'new_active_version' -Default $null
        core_install_authorized=$false
        source_attempts=$attempts
        errors=@(Get-MLLMValue -Object $State -Name 'errors' -Default @())
        generated_at=(Get-Date).ToString('o')
    }
    $jsonPath=Write-MLLMUtf8Json -Value $summary -Path (Join-Path $root 'installer_summary.json')

    $lines=@(
        '# M-LLM Universal Installer Summary',
        '',
        ('Run ID: '+$summary.run_id),
        ('Version ID: '+$summary.version_id),
        ('Stage: '+$summary.stage),
        ('Selected source: '+[string]$summary.selected_source),
        ('Core install authorized: false'),
        ('Source attempts: '+[string]@($summary.source_attempts).Count),
        ('Errors: '+[string]@($summary.errors).Count),
        ('Generated at: '+$summary.generated_at)
    )
    $mdPath=Join-Path $root 'installer_summary.md'
    $utf8=New-Object Text.UTF8Encoding($false)
    [IO.File]::WriteAllLines($mdPath,[string[]]$lines,$utf8)

    return [pscustomobject]@{
        json=$jsonPath
        md=$mdPath
        state=$statePath
        source_attempts=$attemptsPath
        system_profile=$profilePath
        log=$logPath
    }
}

function Export-MLLMInstallerEvidence {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)]$State,
        [Parameter(Mandatory=$true)][ValidateNotNullOrEmpty()][string]$RunRoot,
        [Parameter(Mandatory=$true)][ValidateNotNullOrEmpty()][string]$PreferredEvidenceRoot
    )

    $root=[IO.Path]::GetFullPath($RunRoot)
    $artifacts=Write-MLLMInstallerSummary -State $State -RunRoot $root
    $destinationRoot=$null
    try{
        $preferred=[IO.Path]::GetFullPath($PreferredEvidenceRoot)
        if(Test-Path -LiteralPath $preferred){
            if(-not(Test-Path -LiteralPath $preferred -PathType Container)){throw "Preferred evidence path is not a directory: $preferred"}
        }else{
            New-Item -ItemType Directory -Force -Path $preferred | Out-Null
        }
        $probe=Join-Path $preferred ('.write-test-'+[guid]::NewGuid().ToString('N'))
        [IO.File]::WriteAllText($probe,'ok',(New-Object Text.UTF8Encoding($false)))
        Remove-Item -LiteralPath $probe -Force
        $destinationRoot=$preferred
    }catch{
        $destinationRoot=Join-Path $root 'evidence'
        if(-not(Test-Path -LiteralPath $destinationRoot -PathType Container)){New-Item -ItemType Directory -Force -Path $destinationRoot | Out-Null}
    }

    $runId=[string](Get-MLLMValue -Object $State -Name 'run_id' -Default 'unknown')
    $safeRunId=($runId -replace '[^A-Za-z0-9._-]','_')
    $zip=Join-Path $destinationRoot ('M_LLM_INSTALLER_EVIDENCE_'+$safeRunId+'.zip')
    if(Test-Path -LiteralPath $zip -PathType Leaf){Remove-Item -LiteralPath $zip -Force}

    $files=@(
        $artifacts.state,
        $artifacts.json,
        $artifacts.md,
        $artifacts.source_attempts,
        $artifacts.system_profile,
        $artifacts.log
    )
    foreach($file in $files){
        if(-not(Test-Path -LiteralPath $file -PathType Leaf)){throw "Evidence source file missing: $file"}
    }
    Compress-Archive -LiteralPath $files -DestinationPath $zip -CompressionLevel Optimal -Force
    if(-not(Test-Path -LiteralPath $zip -PathType Leaf)){throw "Evidence ZIP was not created: $zip"}
    if((Get-Item -LiteralPath $zip).Length -le 0){throw "Evidence ZIP is empty: $zip"}
    return $zip
}

Export-ModuleMember -Function Add-MLLMInstallerError,Write-MLLMInstallerSummary,Export-MLLMInstallerEvidence
