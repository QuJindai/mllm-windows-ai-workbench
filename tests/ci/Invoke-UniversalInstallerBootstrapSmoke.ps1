[CmdletBinding()]
param()
$ErrorActionPreference='Stop'
Set-StrictMode -Version 2

$Root=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$module=Join-Path $Root 'installer\InstallerPaths.psm1'
$acqModule=Join-Path $Root 'installer\Acquisition.psm1'
$validationModule=Join-Path $Root 'installer\PackageValidation.psm1'
$manifestPath=Join-Path $Root 'config\source-manifest.json'
$launcher=Join-Path $Root 'installer\Start-UniversalInstaller.ps1'
$cmd=Join-Path $Root 'M_LLM_UNIVERSAL_INSTALLER.cmd'

foreach($path in @($module,$acqModule,$validationModule,$manifestPath,$launcher,$cmd)){
    if(-not(Test-Path -LiteralPath $path -PathType Leaf)){throw "Required universal installer file missing: $path"}
}

Import-Module $module -Force -ErrorAction Stop
Import-Module $acqModule -Force -ErrorAction Stop
Import-Module $validationModule -Force -ErrorAction Stop
$p=Get-MLLMInstallerPaths -RunId 'ci-run' -VersionId 'v1'
$manifest=Get-MLLMSourceManifest -Path $manifestPath

if([string]$manifest.schema -ne 'mllm.universal-installer.sources.v1'){throw 'Default source manifest did not parse'}
if(@($manifest.provider_kinds).Count -ne 5){throw "Unexpected provider kind count: $(@($manifest.provider_kinds).Count)"}
if($p.InstallVersionRoot -notlike "$env:ProgramFiles\M-LLM\Workbench\versions\v1*"){throw "version root is not under Program Files: $($p.InstallVersionRoot)"}
if($p.StagingRoot -notlike "$env:ProgramData\M-LLM\Installer\staging\ci-run*"){throw "staging root is not under ProgramData: $($p.StagingRoot)"}
if($p.CacheRoot -notlike "$env:ProgramData\M-LLM\Installer\cache*"){throw "cache root is not under ProgramData: $($p.CacheRoot)"}
if($p.EvidencePreferredRoot -like '*M_LLM_WORKBENCH_FULL_TEST*'){throw 'legacy Downloads work root leaked into universal installer'}
if($p.ProgramRoot -like '*Downloads*'){throw 'Downloads leaked into ProgramRoot'}
if($p.StagingRoot -like '*Downloads*'){throw 'Downloads leaked into StagingRoot'}

foreach($entry in @($cmd,$launcher)){
    [byte[]]$raw=[IO.File]::ReadAllBytes($entry)
    if($null -ne ($raw | Where-Object {$_ -gt 127} | Select-Object -First 1)){throw "Direct installer entrypoint is not ASCII-only: $entry"}
}

$tokens=$null;$errs=$null
[void][Management.Automation.Language.Parser]::ParseFile($launcher,[ref]$tokens,[ref]$errs)
if(@($errs).Count -gt 0){throw "Universal installer PowerShell entrypoint does not parse: $((@($errs)|ForEach-Object{$_.Message}) -join ' | ')"}

$launcherText=Get-Content -LiteralPath $launcher -Raw -Encoding UTF8
if($launcherText -notmatch [regex]::Escape('Acquisition.psm1')){throw 'Main universal installer does not load Acquisition.psm1'}
if($launcherText -notmatch [regex]::Escape('Get-MLLMSourceManifest')){throw 'Main universal installer does not validate source-manifest.json'}
if($launcherText -notmatch [regex]::Escape('PackageValidation.psm1')){throw 'Main universal installer does not load PackageValidation.psm1'}
if($launcherText -notmatch [regex]::Escape('Test-MLLMPackageHash')){throw 'Main universal installer does not expose package validation capability'}

Write-Host 'UNIVERSAL_BOOTSTRAP_PATHS=PASS'
Write-Host 'UNIVERSAL_ENTRYPOINT_ASCII=PASS'
Write-Host 'UNIVERSAL_SOURCE_MANIFEST=PASS'
Write-Host 'UNIVERSAL_PACKAGE_VALIDATION=PASS'
