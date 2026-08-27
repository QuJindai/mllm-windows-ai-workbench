[CmdletBinding()]
param()
$ErrorActionPreference='Stop'
Set-StrictMode -Version 2

$Root=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$pathsModule=Join-Path $Root 'installer\InstallerPaths.psm1'
$stateModule=Join-Path $Root 'installer\InstallerState.psm1'
$evidenceModule=Join-Path $Root 'installer\InstallerEvidence.psm1'
if(-not(Test-Path -LiteralPath $evidenceModule -PathType Leaf)){throw "InstallerEvidence.psm1 missing: $evidenceModule"}

Import-Module $pathsModule -Force -ErrorAction Stop
Import-Module $stateModule -Force -ErrorAction Stop
Import-Module $evidenceModule -Force -ErrorAction Stop

$temp=Join-Path $env:RUNNER_TEMP ('mllm-evidence-'+[guid]::NewGuid().ToString('N'))
$runRoot=Join-Path $temp 'run'
New-Item -ItemType Directory -Force -Path $runRoot | Out-Null
$runId='ci-evidence-'+([guid]::NewGuid().ToString('N').Substring(0,8))
$versionId='ci-v1'
$paths=Get-MLLMInstallerPaths -RunId $runId -VersionId $versionId
$statePath=Join-Path $runRoot 'installer_state.json'
$state=New-MLLMInstallerState -RunId $runId -VersionId $versionId -Paths $paths
Save-MLLMInstallerState -State $state -Path $statePath | Out-Null

Set-MLLMInstallerStage -State $state -Stage 'ELEVATED' -StatePath $statePath | Out-Null
Set-MLLMInstallerStage -State $state -Stage 'PREFLIGHT' -StatePath $statePath | Out-Null
Set-MLLMInstallerStage -State $state -Stage 'ACQUIRE' -StatePath $statePath | Out-Null
$state.source_attempts=@(
    [pscustomobject]@{source_id='github';kind='github';status='FAILED';error='network unavailable';started_at=(Get-Date).AddSeconds(-2).ToString('o');finished_at=(Get-Date).ToString('o')},
    [pscustomobject]@{source_id='offline-local';kind='local_file';status='FAILED';error='file missing';started_at=(Get-Date).AddSeconds(-1).ToString('o');finished_at=(Get-Date).ToString('o')}
)
Save-MLLMInstallerState -State $state -Path $statePath | Out-Null

try{throw [IO.IOException]::new('ACQUIRE_FAILED fixture')}catch{
    Add-MLLMInstallerError -State $state -Stage 'ACQUIRE' -Exception $_.Exception -Context @{package_id='safe-core';core_install_authorized=$false} -StatePath $statePath | Out-Null
}

[IO.File]::WriteAllText((Join-Path $runRoot 'installer.log'),'fixture installer log',(New-Object Text.UTF8Encoding($false)))
$summary=Write-MLLMInstallerSummary -State $state -RunRoot $runRoot
if(-not(Test-Path -LiteralPath $summary.json -PathType Leaf)){throw 'installer_summary.json missing'}
if(-not(Test-Path -LiteralPath $summary.md -PathType Leaf)){throw 'installer_summary.md missing'}
$s=Get-Content -LiteralPath $summary.json -Raw -Encoding UTF8 | ConvertFrom-Json
if([string]$s.schema -ne 'mllm.universal-installer.summary.v1'){throw "unexpected summary schema: $($s.schema)"}
if([string]$s.run_id -ne $runId){throw 'summary run_id mismatch'}
if([string]$s.stage -ne 'ACQUIRE'){throw "summary stage mismatch: $($s.stage)"}
if([bool]$s.core_install_authorized){throw 'summary must not authorize Core installation'}
if(@($s.source_attempts).Count -ne 2){throw "summary source attempt count mismatch: $(@($s.source_attempts).Count)"}
if(@($s.errors).Count -lt 1){throw 'summary errors missing'}
if([string]$s.errors[0].stage -ne 'ACQUIRE'){throw 'summary error stage mismatch'}
if([string]$s.errors[0].type -notmatch 'IOException'){throw "summary error type missing IOException: $($s.errors[0].type)"}
Write-Host 'INSTALLER_EVIDENCE_SMOKE=PASS'

$preferred=Join-Path $temp 'preferred-is-file'
[IO.File]::WriteAllText($preferred,'not a directory',(New-Object Text.UTF8Encoding($false)))
$zip=Export-MLLMInstallerEvidence -State $state -RunRoot $runRoot -PreferredEvidenceRoot $preferred
if(-not(Test-Path -LiteralPath $zip -PathType Leaf)){throw "evidence ZIP missing: $zip"}
if(-not([IO.Path]::GetFullPath($zip).StartsWith([IO.Path]::GetFullPath($runRoot),[StringComparison]::OrdinalIgnoreCase))){throw "evidence fallback did not use RunRoot: $zip"}

$extract=Join-Path $temp 'extract'
Expand-Archive -LiteralPath $zip -DestinationPath $extract -Force
$required=@('installer_state.json','installer_summary.json','installer_summary.md','source_attempts.json','system_profile.json','installer.log')
foreach($name in $required){
    if(-not(Test-Path -LiteralPath (Join-Path $extract $name) -PathType Leaf)){throw "evidence bundle missing: $name"}
}
$loaded=Read-MLLMInstallerState -Path $statePath
if([string]$loaded.stage -ne 'ACQUIRE'){throw 'evidence fallback corrupted installer state stage'}
Write-Host 'INSTALLER_EVIDENCE_FALLBACK=PASS'
