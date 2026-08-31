[CmdletBinding()]
param()
$ErrorActionPreference='Stop'
Set-StrictMode -Version 2
$root=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$backend=Join-Path $root 'runtime\WorkbenchBackend.ps1'
$tokens=$null;$parseErrors=$null
[void][Management.Automation.Language.Parser]::ParseFile($backend,[ref]$tokens,[ref]$parseErrors)
if(@($parseErrors).Count -gt 0){
  $detail=@($parseErrors | ForEach-Object { 'line='+$_.Extent.StartLineNumber+' col='+$_.Extent.StartColumnNumber+' '+$_.Message }) -join ' | '
  throw ('WORKBENCH_BACKEND_PARSE_FAILED|'+$detail)
}
Write-Host 'WORKBENCH_BACKEND_PARSE=PASS'

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
$developerTools=@($policy.presets.'Developer Tools')
if($developerTools.Count -ne 2 -or $developerTools -notcontains 'git' -or $developerTools -notcontains 'git-lfs'){
    throw ('Developer Tools preset mismatch: '+($developerTools -join ','))
}
$full=@($policy.presets.'Full Setup')
$unexpectedDeveloperTools=@($full | Where-Object {$developerTools -contains [string]$_})
if($unexpectedDeveloperTools.Count -gt 0){throw ('Full Setup includes Developer Tools: '+($unexpectedDeveloperTools -join ','))}
$runtimeTasks=@($registered | Where-Object {$developerTools -notcontains [string]$_.Id} | ForEach-Object {[string]$_.Id})
$missing=@($runtimeTasks | Where-Object {$full -notcontains [string]$_})
if($missing.Count -gt 0){throw ('Full Setup does not cover all runtime tasks: '+($missing -join ','))}
$unexpected=@($full | Where-Object {$runtimeTasks -notcontains [string]$_})
if($unexpected.Count -gt 0){throw ('Full Setup contains unexpected tasks: '+($unexpected -join ','))}
if($full.Count -ne $runtimeTasks.Count){throw ('Full Setup task count mismatch expected='+$runtimeTasks.Count+' actual='+$full.Count)}
Write-Host ('SAFE_CORE_FULL_SETUP=PASS tasks='+($full -join ',')+' developer_tools='+($developerTools -join ','))
Write-Host 'SAFE_CORE_PRESET_INVENTORY=PASS'
