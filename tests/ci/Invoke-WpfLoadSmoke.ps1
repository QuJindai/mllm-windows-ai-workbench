$ErrorActionPreference='Stop'
Set-StrictMode -Version 2
$Root=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Add-Type -AssemblyName PresentationFramework
Add-Type -AssemblyName PresentationCore
Add-Type -AssemblyName WindowsBase
[xml]$xaml=Get-Content -LiteralPath (Join-Path $Root 'gui\Workbench.xaml') -Raw -Encoding UTF8
$reader=New-Object System.Xml.XmlNodeReader $xaml
$window=[Windows.Markup.XamlReader]::Load($reader)
if(-not $window){throw 'XamlReader returned null'}
if(-not $window.FindName('DoctorButton')){throw 'DoctorButton not found'}
if(-not $window.FindName('InstallCoreButton')){throw 'InstallCoreButton not found'}
$window.Close()
Write-Host 'WPF_LOAD_SMOKE=PASS'
