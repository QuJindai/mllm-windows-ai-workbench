[CmdletBinding()]
param()
$ErrorActionPreference='Stop'
Set-StrictMode -Version 2

$Root=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$engine=Join-Path $Root 'installer\InstallerEngine.psm1'
$launcher=Join-Path $Root 'installer\Start-UniversalInstaller.ps1'
foreach($path in @($engine,$launcher)){
    if(-not(Test-Path -LiteralPath $path -PathType Leaf)){throw "Required engine integration file missing: $path"}
}

Import-Module $engine -Force -ErrorAction Stop
if($null -eq (Get-Command Invoke-MLLMFoundationInstall -ErrorAction SilentlyContinue)){throw 'Foundation installer engine command missing'}

$text=Get-Content -LiteralPath $launcher -Raw -Encoding UTF8
foreach($token in @(
    'InstallerEngine.psm1',
    'Invoke-MLLMFoundationInstall',
    'Get-DefaultFoundationPackage',
    "InstallResume={",
    "RetryAcquisition={",
    "ImportOffline={"
)){
    if($text -notmatch [regex]::Escape($token)){throw "Main universal installer engine integration missing token: $token"}
}

if($text -match [regex]::Escape('Foundation engine ready; package execution is gated')){throw 'InstallResume still uses Phase 1 placeholder message'}
if($text -match [regex]::Escape('Acquisition providers are ready; package selection is handled')){throw 'RetryAcquisition still uses placeholder message'}

Write-Host 'UNIVERSAL_ENGINE_INTEGRATION=PASS'
