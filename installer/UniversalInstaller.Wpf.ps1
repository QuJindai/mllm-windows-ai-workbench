[CmdletBinding()]
param(
    $State=$null,
    $Paths=$null,
    [Collections.IDictionary]$Actions=@{},
    [switch]$Smoke
)

$ErrorActionPreference='Stop'
Set-StrictMode -Version 2
Add-Type -AssemblyName PresentationFramework -ErrorAction Stop
Add-Type -AssemblyName PresentationCore -ErrorAction Stop
Add-Type -AssemblyName WindowsBase -ErrorAction Stop

function Get-UiValue {
    param($Object,[Parameter(Mandatory=$true)][string]$Name,$Default=$null)
    if($null -eq $Object){return $Default}
    if($Object -is [Collections.IDictionary]){
        if($Object.Contains($Name)){return $Object[$Name]}
        return $Default
    }
    $prop=$Object.PSObject.Properties[$Name]
    if($null -ne $prop){return $prop.Value}
    return $Default
}

if($null -eq $State){
    $State=[pscustomobject]@{
        stage='INIT'
        stage_sequence=@('INIT','ELEVATED','PREFLIGHT','ACQUIRE','VERIFY_PACKAGE','EXTRACT','VALIDATE_STAGE','INSTALL_VERSION','VERIFY_INSTALL','ACTIVATE','COMPLETE')
        selected_source=$null
        source_attempts=@()
        errors=@()
    }
}
if($null -eq $Paths){
    $Paths=[pscustomobject]@{
        ProgramRoot=if($env:ProgramFiles){Join-Path $env:ProgramFiles 'M-LLM\Workbench'}else{'C:\Program Files\M-LLM\Workbench'}
        EvidencePreferredRoot=if($env:USERPROFILE){Join-Path $env:USERPROFILE 'Downloads\M_LLM_EVIDENCE'}else{'M_LLM_EVIDENCE'}
    }
}

$xamlPath=Join-Path $PSScriptRoot 'UniversalInstaller.xaml'
if(-not(Test-Path -LiteralPath $xamlPath -PathType Leaf)){throw "UniversalInstaller.xaml missing: $xamlPath"}
[xml]$xaml=Get-Content -LiteralPath $xamlPath -Raw -Encoding UTF8
$reader=New-Object System.Xml.XmlNodeReader($xaml)
$window=[Windows.Markup.XamlReader]::Load($reader)
if($null -eq $window){throw 'Universal installer WPF load returned null'}

function C {
    param([Parameter(Mandatory=$true)][string]$Name)
    $control=$window.FindName($Name)
    if($null -eq $control){throw "Universal installer control missing: $Name"}
    return $control
}

$adminStatus=C 'AdminStatusText'
$machineStatus=C 'MachineStatusText'
$installRoot=C 'InstallRootText'
$stageText=C 'StageText'
$sourceText=C 'SourceText'
$progress=C 'ProgressBar'
$statusText=C 'StatusText'
$logText=C 'LogTextBox'
$installResume=C 'InstallResumeButton'
$retryAcquisition=C 'RetryAcquisitionButton'
$importOffline=C 'ImportOfflineButton'
$evidenceButton=C 'EvidenceButton'
$rollbackButton=C 'RollbackButton'

function Test-UiAdministrator {
    try{
        $identity=[Security.Principal.WindowsIdentity]::GetCurrent()
        $principal=New-Object Security.Principal.WindowsPrincipal($identity)
        return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    }catch{return $false}
}

function Get-UiProgress {
    $stage=[string](Get-UiValue -Object $State -Name 'stage' -Default 'INIT')
    $sequence=@(Get-UiValue -Object $State -Name 'stage_sequence' -Default @('INIT'))
    if($sequence.Count -le 1){return 0}
    $index=[Array]::IndexOf([string[]]$sequence,$stage)
    if($index -lt 0){return 0}
    return [Math]::Round((100.0*$index)/($sequence.Count-1),0)
}

function Render-UiState {
    $admin=Test-UiAdministrator
    $adminStatus.Text=if($admin){'Administrator: Yes'}else{'Administrator: No'}
    $machineStatus.Text=([Environment]::OSVersion.VersionString+' | '+[string]$env:PROCESSOR_ARCHITECTURE+' | PowerShell '+[string]$PSVersionTable.PSVersion)
    $installRoot.Text=[string](Get-UiValue -Object $Paths -Name 'ProgramRoot' -Default '-')
    $stage=[string](Get-UiValue -Object $State -Name 'stage' -Default 'INIT')
    $stageText.Text=$stage
    $source=[string](Get-UiValue -Object $State -Name 'selected_source' -Default '')
    if(-not $source){$source='Not selected'}
    $sourceText.Text=$source
    $progress.Value=[double](Get-UiProgress)

    $errors=@(Get-UiValue -Object $State -Name 'errors' -Default @())
    $statusText.Text=if($errors.Count -gt 0){'Attention required - see log and evidence.'}else{'Ready'}

    $lines=New-Object Collections.Generic.List[string]
    foreach($attempt in @(Get-UiValue -Object $State -Name 'source_attempts' -Default @())){
        $sid=[string](Get-UiValue -Object $attempt -Name 'source_id' -Default '?')
        $sstatus=[string](Get-UiValue -Object $attempt -Name 'status' -Default '?')
        $serror=[string](Get-UiValue -Object $attempt -Name 'error' -Default '')
        $lines.Add(('[SOURCE] '+$sid+' '+$sstatus+' '+$serror).Trim())
    }
    foreach($entry in $errors){
        $estage=[string](Get-UiValue -Object $entry -Name 'stage' -Default '?')
        $message=[string](Get-UiValue -Object $entry -Name 'message' -Default '')
        $lines.Add(('[ERROR] '+$estage+' '+$message).Trim())
    }
    if($lines.Count -eq 0){$lines.Add('[INFO] No installer errors recorded.')}
    $logText.Text=($lines -join [Environment]::NewLine)
}

function Append-UiLog {
    param([string]$Line)
    if(-not $Line){return}
    if($logText.Text){$logText.AppendText([Environment]::NewLine)}
    $logText.AppendText($Line)
    $logText.ScrollToEnd()
}

function Invoke-UiAction {
    param([Parameter(Mandatory=$true)][string]$Name,[object[]]$Arguments=@())
    if(-not $Actions.Contains($Name)){
        $statusText.Text=('Action not available in this phase: '+$Name)
        Append-UiLog ('[ACTION] '+$Name+' unavailable')
        return
    }
    try{
        $statusText.Text=('Running: '+$Name)
        Append-UiLog ('[ACTION] '+$Name+' started')
        $result=& $Actions[$Name] @Arguments
        if($null -ne $result){Append-UiLog ('[ACTION] '+$Name+' result: '+[string]$result)}
        $statusText.Text=('Completed: '+$Name)
        Render-UiState
    }catch{
        $statusText.Text=('Failed: '+$Name)
        Append-UiLog ('[ACTION] '+$Name+' failed: '+$_.Exception.Message)
    }
}

$installResume.Add_Click({Invoke-UiAction -Name 'InstallResume'})
$retryAcquisition.Add_Click({Invoke-UiAction -Name 'RetryAcquisition'})
$importOffline.Add_Click({
    $dialog=New-Object Microsoft.Win32.OpenFileDialog
    $dialog.Title='Select M-LLM offline package'
    $dialog.Filter='ZIP packages (*.zip)|*.zip|All files (*.*)|*.*'
    if($dialog.ShowDialog() -eq $true){Invoke-UiAction -Name 'ImportOffline' -Arguments @($dialog.FileName)}
})
$evidenceButton.Add_Click({Invoke-UiAction -Name 'OpenEvidence'})
$rollbackButton.Add_Click({Invoke-UiAction -Name 'Rollback'})

Render-UiState

if($Smoke){
    Write-Host ("UNIVERSAL_INSTALLER_WPF_RUNTIME=PASS stage="+[string]$stageText.Text+" install_root="+[string]$installRoot.Text)
    exit 0
}

[void]$window.ShowDialog()
