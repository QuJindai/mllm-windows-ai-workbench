$ErrorActionPreference='Stop'
Set-StrictMode -Version 2
$Root=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$GuiScript=Join-Path $Root 'gui\Workbench.Wpf.ps1'
if(-not(Test-Path -LiteralPath $GuiScript -PathType Leaf)){throw 'Workbench.Wpf.ps1 missing'}

$text=Get-Content -LiteralPath $GuiScript -Raw -Encoding UTF8
$tokens=$null
$parseErrors=$null
[void][System.Management.Automation.Language.Parser]::ParseFile($GuiScript,[ref]$tokens,[ref]$parseErrors)
if(@($parseErrors).Count -ne 0){throw ('Workbench.Wpf.ps1 parse error: '+(@($parseErrors | ForEach-Object {$_.Message}) -join '; '))}

function Require-Match([string]$Name,[string]$Pattern){
    if($text -notmatch $Pattern){throw "WPF_BINDING_MISSING=$Name"}
    Write-Host "WPF_BINDING_FOUND=$Name"
}

# Doctor must resolve the named control, subscribe Click, and route through
# the asynchronous Doctor operation rather than invoking system tools inline.
Require-Match 'Doctor control lookup' "(?is)\(C\s*['\"]DoctorButton['\"]\)"
Require-Match 'Doctor click subscription' "(?is)\(C\s*['\"]DoctorButton['\"]\)\s*\.\s*Add_Click\s*\("
Require-Match 'Doctor async route' "(?is)DoctorButton['\"]\)\s*\.\s*Add_Click\s*\(.*?-Operation\s*['\"]Doctor['\"]"

# Install Core is intentionally wired through the generic preset loop. The
# binding is safe from PowerShell loop-variable capture because the preset is
# stored on each Button.Tag and read from $this.Tag inside the event handler.
Require-Match 'Install Core preset map' "(?is)@\(\s*['\"]InstallCoreButton['\"]\s*,\s*['\"]Core['\"]\s*\)"
Require-Match 'Preset button lookup' '(?is)\$btn\s*=\s*C\s+\$pair\[0\]'
Require-Match 'Preset stored on button Tag' '(?is)\$btn\.Tag\s*=\s*\$pair\[1\]'
Require-Match 'Preset click subscription' '(?is)\$btn\.Add_Click\s*\('
Require-Match 'Preset read from sender Tag' '(?is)\$preset\s*=\s*\[string\]\$this\.Tag'
Require-Match 'Preset async route' "(?is)-Operation\s*['\"]Preset['\"]\s*-Arguments\s*@\{\s*Preset\s*=\s*\$preset\s*\}"

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
