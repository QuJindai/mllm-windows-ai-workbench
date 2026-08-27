[CmdletBinding()]
param()
$ErrorActionPreference='Stop'
Set-StrictMode -Version 2

$Root=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$activationModule=Join-Path $Root 'installer\Activation.psm1'
$launcher=Join-Path $Root 'installer\Start-UniversalInstaller.ps1'
foreach($path in @($activationModule,$launcher)){
    if(-not(Test-Path -LiteralPath $path -PathType Leaf)){throw "Required activation integration file missing: $path"}
}

Import-Module $activationModule -Force -ErrorAction Stop
foreach($name in @('Install-MLLMVersion','Set-MLLMActiveVersion','Invoke-MLLMRollback')){
    if($null -eq (Get-Command $name -ErrorAction SilentlyContinue)){throw "Activation command missing: $name"}
}

$launcherText=Get-Content -LiteralPath $launcher -Raw -Encoding UTF8
if($launcherText -notmatch [regex]::Escape('Activation.psm1')){throw 'Main universal installer does not load Activation.psm1'}
if($launcherText -notmatch [regex]::Escape('Install-MLLMVersion')){throw 'Main universal installer does not expose version installation capability'}
if($launcherText -notmatch [regex]::Escape('Set-MLLMActiveVersion')){throw 'Main universal installer does not expose version activation capability'}
if($launcherText -notmatch [regex]::Escape('Invoke-MLLMRollback')){throw 'Main universal installer does not expose rollback capability'}

Write-Host 'UNIVERSAL_ACTIVATION_INTEGRATION=PASS'
