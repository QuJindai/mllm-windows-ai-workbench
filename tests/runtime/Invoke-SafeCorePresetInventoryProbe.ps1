[CmdletBinding()]
param()
$ErrorActionPreference='Stop'
Set-StrictMode -Version 2
$root=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
& (Join-Path $root 'Bootstrap_SafeCore.ps1') -ProjectRoot $root | Out-Null
foreach($m in @('Core','State','Detection','Network','Download','Security','Evidence','Runtime')){
  Import-Module (Join-Path $root ('engine\'+$m+'.psm1')) -Force
}
Import-MLLMTasks -ProjectRoot $root
$cmd=Get-Command Invoke-MLLMPreset -ErrorAction Stop
$registered=@(Get-MLLMRegisteredTasks | Select-Object Id,Name,Dependencies)
Write-Host ('SAFE_CORE_TASK_COUNT='+$registered.Count)
$registered | ForEach-Object { Write-Host ('SAFE_CORE_TASK id='+[string]$_.Id+' name='+[string]$_.Name+' deps='+(@($_.Dependencies)-join ',')) }
$definition=[string]$cmd.Definition
Write-Host 'SAFE_CORE_PRESET_DEFINITION_BEGIN'
Write-Host $definition
Write-Host 'SAFE_CORE_PRESET_DEFINITION_END'
if($registered.Count -lt 8){throw ('Expected at least 8 registered component tasks, got '+$registered.Count)}
Write-Host 'SAFE_CORE_PRESET_INVENTORY=PASS'
