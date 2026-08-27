[CmdletBinding()]
param()
$ErrorActionPreference='Stop'
$Root=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$entry=Join-Path $Root 'M_LLM_GUI_PREFLIGHT.ps1'
if(-not(Test-Path -LiteralPath $entry -PathType Leaf)){throw 'M_LLM_GUI_PREFLIGHT.ps1 missing'}

$dataRoot=Join-Path $env:RUNNER_TEMP 'mllm-gui-preflight-entrypoint'
if(Test-Path -LiteralPath $dataRoot){Remove-Item -LiteralPath $dataRoot -Recurse -Force}
New-Item -ItemType Directory -Force -Path $dataRoot | Out-Null

$out=@(& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $entry -DataRoot $dataRoot -NetworkMode OFFLINE_CACHE 2>&1)
$rc=$LASTEXITCODE
$text=($out -join "`n")
Write-Host $text
if($rc -ne 0){throw "GUI preflight entrypoint failed rc=$rc"}
if($text -notmatch 'GUI_PREFLIGHT=PASS'){throw "GUI preflight PASS marker missing: $text"}

$reportPath=Join-Path $dataRoot 'gui_preflight.json'
if(-not(Test-Path -LiteralPath $reportPath -PathType Leaf)){throw "GUI preflight report missing: $reportPath"}
$r=Get-Content -LiteralPath $reportPath -Raw -Encoding UTF8 | ConvertFrom-Json
if([string]$r.schema -ne 'mllm.gui-preflight.v1'){throw "Unexpected GUI preflight schema: $($r.schema)"}
if([string]$r.mode -ne 'NON_INSTALLING'){throw "Unexpected GUI preflight mode: $($r.mode)"}
if([bool]$r.core_install_authorized){throw 'GUI preflight must never authorize Core install'}
if([int]$r.install_actions_executed -ne 0){throw "GUI preflight executed install actions: $($r.install_actions_executed)"}
if([int]$r.network_actions_executed -ne 0){throw "GUI preflight executed network actions: $($r.network_actions_executed)"}
if([string]$r.network_mode -ne 'OFFLINE_CACHE'){throw "GUI preflight network mode mismatch: $($r.network_mode)"}
if([int]$r.snapshot_errors -ne 0){throw "GUI preflight snapshot errors: $($r.snapshot_errors)"}
if([int]$r.task_count -lt 8){throw "GUI preflight task count too small: $($r.task_count)"}
if([string]$r.status -ne 'PASS'){throw "GUI preflight report status not PASS: $($r.status)"}

$commandScopePattern='CommandNotFoundException|not recognized as the name of a cmdlet|\u65E0\u6CD5\u5C06.+\u8BC6\u522B\u4E3A'
$bad=@($r.tasks | Where-Object { ([string]$_.summary) -match $commandScopePattern })
if($bad.Count -gt 0){throw "GUI preflight leaked command visibility errors: $($bad.id -join ',')"}

# Build the Chinese phrase from character codes so this test file is also
# source-encoding independent while proving the Unicode-regex branch works.
$zh=[string]::Concat(
    [char]0x65E0,[char]0x6CD5,[char]0x5C06,
    'Find-MLLMPython',
    [char]0x8BC6,[char]0x522B,[char]0x4E3A
)
if($zh -notmatch $commandScopePattern){throw 'Unicode command-scope regex did not match the Chinese PowerShell diagnostic form'}

foreach($id in @('llama-cpp','local-api','modelscope','python','qwen35-4b','web-workbench')){
    if(-not(@($r.tasks | Where-Object { $_.id -eq $id }).Count)){throw "GUI preflight missing required task: $id"}
}
Write-Host "GUI_PREFLIGHT_ENTRYPOINT_SMOKE=PASS tasks=$($r.task_count) snapshot_errors=$($r.snapshot_errors) unicode_regex=PASS"
