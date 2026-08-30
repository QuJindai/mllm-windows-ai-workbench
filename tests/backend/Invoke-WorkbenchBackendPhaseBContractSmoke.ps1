[CmdletBinding()]
param()
$ErrorActionPreference='Stop'
Set-StrictMode -Version 2
$root=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$backend=Join-Path $root 'runtime\WorkbenchBackend.ps1'
if(-not(Test-Path -LiteralPath $backend -PathType Leaf)){throw "WorkbenchBackend.ps1 missing: $backend"}
$content=Get-Content -LiteralPath $backend -Raw
$match=[regex]::Match($content,'(?s)\$MethodTable\s*=\s*@\{(?<body>.*?)\n\}')
if(-not $match.Success){throw 'MethodTable allowlist not found'}
$keys=@([regex]::Matches($match.Groups['body'].Value,"(?m)^\s*'([^']+)'\s*=") | ForEach-Object {$_.Groups[1].Value})
$expected=@(
  'system.ping','dashboard.snapshot','doctor.snapshot','installer.snapshot',
  'system.capabilities','models.snapshot','models.verify','models.import','models.activate',
  'services.snapshot','service.start','service.stop','service.restart','service.logs',
  'components.presets','components.install_preset'
)
$missing=@($expected | Where-Object {$keys -notcontains $_})
$extra=@($keys | Where-Object {$expected -notcontains $_})
if($missing.Count -gt 0){throw ('Phase B backend methods missing: '+($missing -join ','))}
if($extra.Count -gt 0){throw ('Unexpected backend methods exposed: '+($extra -join ','))}
$forbidden=@($keys | Where-Object {$_ -match '(?i)exec|command|shell|script|eval|powershell|pid|process'})
if($forbidden.Count -gt 0){throw ('Forbidden backend method exposed: '+($forbidden -join ','))}
if($content -notmatch 'WorkbenchRuntimeAdapter\.psm1'){throw 'Backend does not load shared WorkbenchRuntimeAdapter.psm1'}
foreach($operation in @(
  'Get-MLLMModelInventory','Test-MLLMWorkbenchModel','Import-MLLMManagedModel','Set-MLLMActiveModel',
  'Get-MLLMWorkbenchServices','Start-MLLMWorkbenchService','Stop-MLLMWorkbenchService','Restart-MLLMWorkbenchService','Get-MLLMWorkbenchServiceLogs',
  'Import-MLLMTasks','Invoke-MLLMPreset'
)){
  if($content -notmatch [regex]::Escape($operation)){throw "Backend does not route fixed runtime operation: $operation"}
}
foreach($presetId in @('full-setup','local-ai-fast','core','web-workbench','developer-tools')){
  if($content -notmatch [regex]::Escape($presetId)){throw "Backend preset allowlist missing: $presetId"}
}
Write-Host ('PHASE_B_BACKEND_CONTRACT=PASS methods='+($keys -join ','))
