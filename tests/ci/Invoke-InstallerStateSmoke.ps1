[CmdletBinding()]
param()
$ErrorActionPreference='Stop'
Set-StrictMode -Version 2

$Root=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$pathsModule=Join-Path $Root 'installer\InstallerPaths.psm1'
$stateModule=Join-Path $Root 'installer\InstallerState.psm1'
if(-not(Test-Path -LiteralPath $stateModule -PathType Leaf)){throw "InstallerState.psm1 missing: $stateModule"}

Import-Module $pathsModule -Force -ErrorAction Stop
Import-Module $stateModule -Force -ErrorAction Stop

$runId='ci-state-'+([guid]::NewGuid().ToString('N').Substring(0,8))
$versionId='ci-v1'
$testRoot=Join-Path $env:RUNNER_TEMP $runId
New-Item -ItemType Directory -Force -Path $testRoot | Out-Null
$statePath=Join-Path $testRoot 'installer_state.json'
$paths=Get-MLLMInstallerPaths -RunId $runId -VersionId $versionId

$state=New-MLLMInstallerState -RunId $runId -VersionId $versionId -Paths $paths
$expected=@('INIT','ELEVATED','PREFLIGHT','ACQUIRE','VERIFY_PACKAGE','EXTRACT','VALIDATE_STAGE','INSTALL_VERSION','VERIFY_INSTALL','ACTIVATE','COMPLETE')
if((@($state.stage_sequence) -join '|') -ne ($expected -join '|')){throw "Unexpected stage sequence: $(@($state.stage_sequence) -join ',')"}
if([string]$state.stage -ne 'INIT'){throw "Initial stage must be INIT, got $($state.stage)"}

Set-MLLMInstallerStage -State $state -Stage 'ELEVATED' -StatePath $statePath | Out-Null
Set-MLLMInstallerStage -State $state -Stage 'PREFLIGHT' -StatePath $statePath | Out-Null
$state.selected_source='offline-local'
Save-MLLMInstallerState -State $state -Path $statePath

$loaded=Read-MLLMInstallerState -Path $statePath
if($null -eq $loaded){throw 'Reloaded installer state is null'}
if([string]$loaded.run_id -ne $runId){throw 'RunId did not survive resume'}
if([string]$loaded.version_id -ne $versionId){throw 'VersionId did not survive resume'}
if([string]$loaded.selected_source -ne 'offline-local'){throw 'selected_source did not survive resume'}
if(-not(Test-MLLMStageComplete -State $loaded -Stage 'PREFLIGHT')){throw 'PREFLIGHT completion did not survive resume'}
if(Test-MLLMStageComplete -State $loaded -Stage 'ACQUIRE'){throw 'ACQUIRE must not be complete'}
if([string]$loaded.stage -ne 'PREFLIGHT'){throw "Resume stage mismatch: $($loaded.stage)"}

$raw=Get-Content -LiteralPath $statePath -Raw -Encoding UTF8
if($raw -notmatch 'mllm.universal-installer.state.v1'){throw 'State schema marker missing'}
if(Test-Path -LiteralPath ($statePath+'.tmp')){throw 'Atomic state temp file leaked after save'}

Write-Host "INSTALLER_STATE_SMOKE=PASS resume_stage=$($loaded.stage) run_id=$runId"
