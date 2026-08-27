[CmdletBinding()]
param()
$ErrorActionPreference='Stop'
Set-StrictMode -Version 2

$Root=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$launcher=Join-Path $Root 'installer\Start-UniversalInstaller.ps1'
$wpf=Join-Path $Root 'installer\UniversalInstaller.Wpf.ps1'
foreach($path in @($launcher,$wpf)){
    if(-not(Test-Path -LiteralPath $path -PathType Leaf)){throw "Required WPF integration file missing: $path"}
}

$text=Get-Content -LiteralPath $launcher -Raw -Encoding UTF8
foreach($token in @('UniversalInstaller.Wpf.ps1','-State $state','-Paths $paths','InstallResume','RetryAcquisition','ImportOffline','OpenEvidence','Rollback')){
    if($text -notmatch [regex]::Escape($token)){throw "Main universal installer WPF integration missing token: $token"}
}
if($text -notmatch '\[switch\]\$NoGui'){throw 'Main universal installer does not expose -NoGui for automation/headless execution'}
if($text -notmatch '\[switch\]\$GuiSmoke'){throw 'Main universal installer does not expose -GuiSmoke for WPF integration verification'}

Write-Host 'UNIVERSAL_WPF_INTEGRATION=PASS'
