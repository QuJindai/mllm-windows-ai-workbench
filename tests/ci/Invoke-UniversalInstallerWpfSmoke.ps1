[CmdletBinding()]
param()
$ErrorActionPreference='Stop'
Set-StrictMode -Version 2

$Root=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$xamlPath=Join-Path $Root 'installer\UniversalInstaller.xaml'
$wpfPath=Join-Path $Root 'installer\UniversalInstaller.Wpf.ps1'
foreach($path in @($xamlPath,$wpfPath)){
    if(-not(Test-Path -LiteralPath $path -PathType Leaf)){throw "Universal installer WPF file missing: $path"}
}

[xml]$xml=Get-Content -LiteralPath $xamlPath -Raw -Encoding UTF8
if($null -eq $xml){throw 'Universal installer XAML XML parse returned null'}

Add-Type -AssemblyName PresentationFramework -ErrorAction Stop
Add-Type -AssemblyName PresentationCore -ErrorAction Stop
Add-Type -AssemblyName WindowsBase -ErrorAction Stop
$xamlText=Get-Content -LiteralPath $xamlPath -Raw -Encoding UTF8
$reader=New-Object System.Xml.XmlNodeReader([xml]$xamlText)
$window=[Windows.Markup.XamlReader]::Load($reader)
if($null -eq $window){throw 'Universal installer XAML load returned null'}

$required=@(
    'AdminStatusText','MachineStatusText','InstallRootText','StageText','SourceText',
    'ProgressBar','StatusText','InstallResumeButton','RetryAcquisitionButton',
    'ImportOfflineButton','EvidenceButton','RollbackButton','LogTextBox'
)
foreach($name in $required){
    if($null -eq $window.FindName($name)){throw "Universal installer control missing: $name"}
}
Write-Host 'UNIVERSAL_INSTALLER_WPF_LOAD=PASS'

$scriptText=Get-Content -LiteralPath $wpfPath -Raw -Encoding UTF8
$forbidden=@(
    'Start-BitsTransfer','Invoke-WebRequest','System.Net.Http','HttpClient',
    'Copy-Item','Move-Item','Install-MLLMVersion','Set-MLLMActiveVersion',
    'Save-MLLMActivePointer','current.json','File]::Replace','File.Replace'
)
foreach($token in $forbidden){
    if($scriptText -match [regex]::Escape($token)){throw "WPF layer contains forbidden install/network primitive: $token"}
}
Write-Host 'UNIVERSAL_INSTALLER_WPF_NO_DIRECT_INSTALL=PASS'

$bindings=[ordered]@{
    InstallResumeButton='InstallResume'
    RetryAcquisitionButton='RetryAcquisition'
    ImportOfflineButton='ImportOffline'
    EvidenceButton='OpenEvidence'
    RollbackButton='Rollback'
}
foreach($button in $bindings.Keys){
    if($scriptText -notmatch [regex]::Escape($button)){throw "WPF script does not reference button: $button"}
    if($scriptText -notmatch [regex]::Escape($bindings[$button])){throw "WPF script does not route action: $($bindings[$button])"}
}
if($scriptText -notmatch [regex]::Escape('OpenFileDialog')){throw 'Import Offline action does not expose a file picker'}
Write-Host 'UNIVERSAL_INSTALLER_WPF_BINDINGS=PASS'

$tokens=$null;$errors=$null
[void][Management.Automation.Language.Parser]::ParseFile($wpfPath,[ref]$tokens,[ref]$errors)
if(@($errors).Count -gt 0){throw "Universal installer WPF script parse failed: $((@($errors)|ForEach-Object{$_.Message}) -join ' | ')"}

$out=@(& powershell.exe -NoProfile -STA -ExecutionPolicy Bypass -File $wpfPath -Smoke 2>&1)
$rc=$LASTEXITCODE
$text=($out -join "`n")
Write-Host $text
if($rc -ne 0){throw "Universal installer WPF runtime smoke failed rc=$rc"}
if($text -notmatch 'UNIVERSAL_INSTALLER_WPF_RUNTIME=PASS'){throw "WPF runtime PASS marker missing: $text"}
if($text -notmatch 'stage=INIT'){throw "WPF runtime did not render INIT state: $text"}
Write-Host 'UNIVERSAL_INSTALLER_WPF_RUNTIME_GATE=PASS'
