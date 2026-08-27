[CmdletBinding()]
param()
$ErrorActionPreference='Stop'
Set-StrictMode -Version 2

$Root=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$module=Join-Path $Root 'installer\InstallerEvidence.psm1'
$launcher=Join-Path $Root 'installer\Start-UniversalInstaller.ps1'
foreach($path in @($module,$launcher)){
    if(-not(Test-Path -LiteralPath $path -PathType Leaf)){throw "Required evidence integration file missing: $path"}
}

Import-Module $module -Force -ErrorAction Stop
foreach($name in @('Add-MLLMInstallerError','Write-MLLMInstallerSummary','Export-MLLMInstallerEvidence')){
    if($null -eq (Get-Command $name -ErrorAction SilentlyContinue)){throw "Evidence command missing: $name"}
}

$launcherText=Get-Content -LiteralPath $launcher -Raw -Encoding UTF8
if($launcherText -notmatch [regex]::Escape('InstallerEvidence.psm1')){throw 'Main universal installer does not load InstallerEvidence.psm1'}
if($launcherText -notmatch [regex]::Escape('Add-MLLMInstallerError')){throw 'Main universal installer does not expose structured error capability'}
if($launcherText -notmatch [regex]::Escape('Write-MLLMInstallerSummary')){throw 'Main universal installer does not expose summary capability'}
if($launcherText -notmatch [regex]::Escape('Export-MLLMInstallerEvidence')){throw 'Main universal installer does not expose evidence export capability'}

Write-Host 'UNIVERSAL_EVIDENCE_INTEGRATION=PASS'
