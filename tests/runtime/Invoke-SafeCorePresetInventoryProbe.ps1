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
if($registered.Count -ne 8){throw ('Expected exactly 8 registered component tasks, got '+$registered.Count)}
$policy=Get-Content -LiteralPath (Join-Path $root 'config\task-policy.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$full=@($policy.presets.'Full Setup')
$missing=@($registered | Where-Object {$full -notcontains [string]$_.Id} | ForEach-Object {[string]$_.Id})
if($missing.Count -gt 0){throw ('Full Setup does not cover all registered tasks: '+($missing -join ','))}
if($full.Count -ne $registered.Count){throw ('Full Setup task count mismatch expected='+$registered.Count+' actual='+$full.Count)}
Write-Host ('SAFE_CORE_FULL_SETUP=PASS tasks='+($full -join ','))
Write-Host 'SAFE_CORE_PRESET_INVENTORY=PASS'
