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

function Require-Contains([string]$Name,[string]$Needle){
    if(-not $text.Contains($Needle)){throw "WPF_BINDING_MISSING=$Name"}
    Write-Host "WPF_BINDING_FOUND=$Name"
}

# Doctor must resolve the named control, subscribe Click, and route through
# the asynchronous Doctor operation rather than invoking system tools inline.
Require-Contains 'Doctor click route' '(C ''DoctorButton'').Add_Click({Run-AsyncJob -Label ''Running Doctor'' -Operation ''Doctor'''

# Install Core is intentionally wired through the generic preset loop. The
# binding is safe from PowerShell loop-variable capture because the preset is
# stored on each Button.Tag and read from $this.Tag inside the event handler.
Require-Contains 'Install Core preset map' '@(''InstallCoreButton'',''Core'')'
Require-Contains 'Preset button lookup' '$btn=C $pair[0]'
Require-Contains 'Preset stored on button Tag' '$btn.Tag=$pair[1]'
Require-Contains 'Preset click subscription' '$btn.Add_Click({'
Require-Contains 'Preset read from sender Tag' '$preset=[string]$this.Tag'
Require-Contains 'Preset async route' '-Operation ''Preset'' -Arguments @{Preset=$preset}'

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
