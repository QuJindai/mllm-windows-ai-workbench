$ErrorActionPreference='Stop'
Set-StrictMode -Version 2
$Root=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$GuiScript=Join-Path $Root 'gui\Workbench.Wpf.ps1'
if(-not(Test-Path -LiteralPath $GuiScript -PathType Leaf)){throw 'Workbench.Wpf.ps1 missing'}

$text=Get-Content -LiteralPath $GuiScript -Raw -Encoding UTF8
$sourceLines=@(Get-Content -LiteralPath $GuiScript -Encoding UTF8)
$tokens=$null
$parseErrors=$null
[void][System.Management.Automation.Language.Parser]::ParseFile($GuiScript,[ref]$tokens,[ref]$parseErrors)
if(@($parseErrors).Count -ne 0){throw ('Workbench.Wpf.ps1 parse error: '+(@($parseErrors | ForEach-Object {$_.Message}) -join '; '))}

# Bounded context around the event-wiring section. This is intentionally
# temporary diagnostic evidence while the GUI binding contract is hardened.
$start=125
$end=[Math]::Min(185,$sourceLines.Count)
for($lineNo=$start;$lineNo -le $end;$lineNo++){
    Write-Host ("WPF_SOURCE_CONTEXT line={0}: {1}" -f $lineNo,$sourceLines[$lineNo-1])
}

function Require-Match([string]$Name,[string]$Pattern){
    if($text -notmatch $Pattern){throw "WPF_BINDING_MISSING=$Name"}
    Write-Host "WPF_BINDING_FOUND=$Name"
}

# Presence in XAML is already checked by Invoke-WpfLoadSmoke.ps1. These gates
# verify that the code-behind actually subscribes the two field-critical
# buttons and routes them through the centralized Doctor/preset orchestration.
Require-Match 'DoctorButton.Add_Click' '(?is)\$DoctorButton\s*\.\s*Add_Click\s*\('
Require-Match 'InstallCoreButton.Add_Click' '(?is)\$InstallCoreButton\s*\.\s*Add_Click\s*\('
Require-Match 'Doctor orchestration' '(?i)Invoke-MLLMDoctor'
Require-Match 'Preset orchestration' '(?i)Invoke-MLLMPreset'
Require-Match 'Core preset reference' '(?i)[\''\"]Core[\''\"]'

# GUI code must not bypass Safe Core and invoke machine-wide installers or
# privileged configuration tools directly.
$forbidden=@(
    '(?i)winget\s+install',
    '(?i)msiexec(?:\.exe)?',
    '(?i)pnputil(?:\.exe)?',
    '(?i)dism(?:\.exe)?',
    '(?i)schtasks(?:\.exe)?\s+/create',
    '(?i)reg(?:\.exe)?\s+(add|delete)'
)
foreach($pattern in $forbidden){
    if($text -match $pattern){throw "WPF_FORBIDDEN_DIRECT_SYSTEM_ACTION pattern=$pattern"}
}

Write-Host 'WPF_BINDING_SMOKE=PASS'
