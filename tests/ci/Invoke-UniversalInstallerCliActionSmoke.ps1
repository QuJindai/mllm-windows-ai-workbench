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

Write-Host 'UNIVERSAL_INSTALLER_CLI_ACTION=PASS none=PASS missing_offline=PASS invalid=PASS forwarding=PASS'
