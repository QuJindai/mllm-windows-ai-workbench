[CmdletBinding()]
param()
$ErrorActionPreference='Stop'
Set-StrictMode -Version 2
$root=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$script=Join-Path $root 'installer\Start-UniversalInstaller.ps1'
if(-not(Test-Path -LiteralPath $script -PathType Leaf)){throw "Start-UniversalInstaller.ps1 missing: $script"}

$command=Get-Command $script -ErrorAction Stop
foreach($required in @('Action','OfflinePackagePath')){
    if(-not $command.Parameters.ContainsKey($required)){throw "Installer CLI parameter missing: $required"}
}
$actionAttributes=@($command.Parameters['Action'].Attributes | Where-Object { $_ -is [Management.Automation.ValidateSetAttribute] })
if($actionAttributes.Count -ne 1){throw 'Action ValidateSet attribute missing'}
$expected=@('None','InstallResume','RetryAcquisition','ImportOffline','Rollback')
$actual=@($actionAttributes[0].ValidValues)
if(($actual -join '|') -ne ($expected -join '|')){throw ('Unexpected Action values: '+($actual -join ','))}

$content=Get-Content -LiteralPath $script -Raw
if($content -notmatch 'if\(\$NoGui\s+-and\s+\$Action\s+-eq\s+''None''\)'){throw 'NoGui early exit is not Action-aware'}
if($content -notmatch '\$forward.+-Action'){throw 'UAC forwarding does not preserve Action'}
if($content -notmatch '\$forward.+-OfflinePackagePath'){throw 'UAC forwarding does not preserve OfflinePackagePath'}

function Invoke-InstallerProcess {
    param([string[]]$Arguments)
    $stdout=Join-Path $env:RUNNER_TEMP ('mllm-cli-'+[guid]::NewGuid().ToString('N')+'.out.txt')
    $stderr=Join-Path $env:RUNNER_TEMP ('mllm-cli-'+[guid]::NewGuid().ToString('N')+'.err.txt')
    $all=@('-NoProfile','-ExecutionPolicy','Bypass','-File',$script)+$Arguments
    $p=Start-Process -FilePath 'powershell.exe' -ArgumentList $all -Wait -PassThru -NoNewWindow -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    $text=((Get-Content -LiteralPath $stdout -Raw -ErrorAction SilentlyContinue)+"`n"+(Get-Content -LiteralPath $stderr -Raw -ErrorAction SilentlyContinue))
    Remove-Item -LiteralPath $stdout,$stderr -Force -ErrorAction SilentlyContinue
    return [pscustomobject]@{ExitCode=$p.ExitCode;Text=$text}
}

$run='cli_none_'+[guid]::NewGuid().ToString('N').Substring(0,8)
$none=Invoke-InstallerProcess -Arguments @('-NoElevate','-NoGui','-Action','None','-RunId',$run,'-VersionId','phase-a-cli-none')
if($none.ExitCode -ne 0){throw ('Action None failed rc='+$none.ExitCode+' output='+$none.Text)}
if($none.Text -notmatch 'UNIVERSAL_INSTALLER_NEXT='){throw 'Action None did not preserve bootstrap-only NoGui behavior'}

$missing=Invoke-InstallerProcess -Arguments @('-NoElevate','-NoGui','-Action','ImportOffline','-RunId',('cli_missing_'+[guid]::NewGuid().ToString('N').Substring(0,8)),'-VersionId','phase-a-cli-missing')
if($missing.ExitCode -eq 0){throw 'ImportOffline without OfflinePackagePath unexpectedly succeeded'}
if($missing.Text -notmatch 'OfflinePackagePath is required'){throw ('Missing offline path error is not explicit: '+$missing.Text)}

$invalid=Invoke-InstallerProcess -Arguments @('-NoElevate','-NoGui','-Action','NotARealAction','-RunId',('cli_invalid_'+[guid]::NewGuid().ToString('N').Substring(0,8)))
if($invalid.ExitCode -eq 0){throw 'Invalid Action unexpectedly passed parameter validation'}

# Action mode is consumed by the Desktop Installation Center, which decides
# success from the child process exit code. Exercise known negative states in
# isolated roots so a user-visible action can never print PASS and exit 0 when
# no operation was actually possible.
$oldProgramData=$env:ProgramData
$oldProgramFiles=$env:ProgramFiles
$oldUserProfile=$env:USERPROFILE
$isolation=Join-Path $env:RUNNER_TEMP ('mllm-cli-isolated-'+[guid]::NewGuid().ToString('N'))
try{
    $env:ProgramData=Join-Path $isolation 'ProgramData'
    $env:ProgramFiles=Join-Path $isolation 'ProgramFiles'
    $env:USERPROFILE=Join-Path $isolation 'UserProfile'
    foreach($dir in @($env:ProgramData,$env:ProgramFiles,$env:USERPROFILE)){New-Item -ItemType Directory -Force -Path $dir | Out-Null}

    $noPackage=Invoke-InstallerProcess -Arguments @(
        '-NoElevate','-NoGui','-Action','InstallResume',
        '-RunId',('cli_no_package_'+[guid]::NewGuid().ToString('N').Substring(0,8)),
        '-VersionId','phase-a-cli-no-package',
        '-SourceManifestPath',(Join-Path $root 'config\source-manifest.json')
    )
    if($noPackage.ExitCode -eq 0){throw ('InstallResume without a foundation package incorrectly succeeded: '+$noPackage.Text)}
    if($noPackage.Text -notmatch 'No workbench foundation package'){throw ('InstallResume no-package failure is not explicit: '+$noPackage.Text)}

    $noRollback=Invoke-InstallerProcess -Arguments @(
        '-NoElevate','-NoGui','-Action','Rollback',
        '-RunId',('cli_no_rollback_'+[guid]::NewGuid().ToString('N').Substring(0,8)),
        '-VersionId','phase-a-cli-no-rollback',
        '-SourceManifestPath',(Join-Path $root 'config\source-manifest.json')
    )
    if($noRollback.ExitCode -eq 0){throw ('Rollback without an active pointer incorrectly succeeded: '+$noRollback.Text)}
    if($noRollback.Text -notmatch 'No active version pointer'){throw ('Rollback no-pointer failure is not explicit: '+$noRollback.Text)}
}finally{
    $env:ProgramData=$oldProgramData
    $env:ProgramFiles=$oldProgramFiles
    $env:USERPROFILE=$oldUserProfile
    Remove-Item -LiteralPath $isolation -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host 'UNIVERSAL_INSTALLER_CLI_ACTION=PASS none=PASS missing_offline=PASS invalid=PASS fail_closed=PASS forwarding=PASS'
