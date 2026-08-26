[CmdletBinding()]
param(
    [string]$DataRoot='',
    [switch]$SkipEventLog,
    [switch]$SkipDriverInventory
)

$ErrorActionPreference='Stop'
Set-StrictMode -Version 2
$ProjectRoot=$PSScriptRoot
$StartedAt=Get-Date

if(-not $DataRoot){
    $downloadRoot=Join-Path $env:USERPROFILE 'Downloads'
    if(-not(Test-Path -LiteralPath $downloadRoot -PathType Container)){$downloadRoot=$env:TEMP}
    $DataRoot=Join-Path $downloadRoot 'M_LLM_PHYSICAL_PREFLIGHT'
}
$DataRoot=[System.IO.Path]::GetFullPath($DataRoot)
$RunDir=Join-Path $DataRoot ('physical_preflight\'+(Get-Date -Format 'yyyyMMdd_HHmmss_fff'))
New-Item -ItemType Directory -Force -Path $RunDir | Out-Null

$ReportPath=Join-Path $RunDir 'physical_preflight.json'
$SummaryPath=Join-Path $RunDir 'physical_preflight.md'
$CliLogPath=Join-Path $RunDir 'cli.log'
$DoctorLogPath=Join-Path $RunDir 'doctor.log'
$EventPath=Join-Path $RunDir 'system_events.json'
$DriverPath=Join-Path $RunDir 'drivers.json'
$BundlePath=Join-Path $DataRoot ('M_LLM_PHYSICAL_PREFLIGHT_'+(Get-Date -Format 'yyyyMMdd_HHmmss')+'.zip')

function Get-ElevationState {
    try{
        $identity=[Security.Principal.WindowsIdentity]::GetCurrent()
        $principal=New-Object Security.Principal.WindowsPrincipal($identity)
        return [bool]$principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    }catch{
        return $false
    }
}

function Invoke-ChildPowerShell {
    param([string[]]$Arguments,[string]$LogPath)
    $ps51=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    if(-not(Test-Path -LiteralPath $ps51 -PathType Leaf)){throw 'Windows PowerShell 5.1 executable missing'}
    $output=@(& $ps51 @Arguments 2>&1)
    $rc=$LASTEXITCODE
    $output | Out-File -LiteralPath $LogPath -Encoding utf8
    [pscustomobject]@{exit_code=[int]$rc;log=$LogPath;line_count=@($output).Count}
}

function Write-PreflightArtifacts {
    param([hashtable]$Report)
    $Report.finished_at=(Get-Date).ToString('o')
    $Report.duration_seconds=[Math]::Round(((Get-Date)-$StartedAt).TotalSeconds,3)
    $Report | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $ReportPath -Encoding UTF8

    $lines=@(
        '# M-LLM physical preflight',
        '',
        ('- Mode: '+$Report.mode),
        ('- Gate: '+$Report.release_gate),
        ('- Core install authorized: '+$Report.core_install_authorized),
        ('- Elevated: '+$Report.host.elevated),
        ('- Windows: '+$Report.host.os_caption+' '+$Report.host.os_version+' build '+$Report.host.os_build),
        ('- PowerShell: '+$Report.host.powershell),
        ('- Bootstrap: '+$Report.bootstrap.status),
        ('- CLI exit code: '+$Report.cli.exit_code),
        ('- Doctor exit code: '+$Report.doctor.exit_code),
        ('- Doctor evidence files: '+$Report.doctor.evidence_count),
        ('- Event inventory: '+$Report.system_events.status),
        ('- Driver inventory: '+$Report.drivers.status),
        '',
        'This preflight does not authorize or perform Core installation. Review the evidence before any physical-machine install step.'
    )
    $lines | Set-Content -LiteralPath $SummaryPath -Encoding UTF8
}

$elevated=Get-ElevationState
$osCaption='unknown'
$osVersion='unknown'
$osBuild='unknown'
$osArch='unknown'
$lastBoot=$null
$manufacturer='unknown'
$model='unknown'
$memoryBytes=0
$diskInventory=@()
$hostProbeError=$null
try{
    $os=Get-CimInstance -ClassName Win32_OperatingSystem -ErrorAction Stop
    $cs=Get-CimInstance -ClassName Win32_ComputerSystem -ErrorAction Stop
    $osCaption=[string]$os.Caption
    $osVersion=[string]$os.Version
    $osBuild=[string]$os.BuildNumber
    $osArch=[string]$os.OSArchitecture
    $lastBoot=$os.LastBootUpTime
    $manufacturer=[string]$cs.Manufacturer
    $model=[string]$cs.Model
    $memoryBytes=[int64]$cs.TotalPhysicalMemory
    $diskInventory=@(Get-CimInstance -ClassName Win32_LogicalDisk -Filter 'DriveType=3' -ErrorAction Stop | ForEach-Object {
        [pscustomobject]@{
            device_id=[string]$_.DeviceID
            size_bytes=[int64]$_.Size
            free_bytes=[int64]$_.FreeSpace
        }
    })
}catch{
    $hostProbeError=$_.Exception.Message
}

$Report=[ordered]@{
    schema='mllm.physical-preflight.v1'
    mode='NON_INSTALLING'
    release_gate='BLOCKED_PENDING_EVIDENCE_REVIEW'
    core_install_authorized=$false
    install_actions_executed=0
    network_actions_executed=0
    started_at=$StartedAt.ToString('o')
    finished_at=$null
    duration_seconds=0
    project_root=$ProjectRoot
    data_root=$DataRoot
    run_dir=$RunDir
    evidence_bundle=$BundlePath
    host=[ordered]@{
        computer_name=[string]$env:COMPUTERNAME
        user_name=[string]$env:USERNAME
        elevated=$elevated
        os_caption=$osCaption
        os_version=$osVersion
        os_build=$osBuild
        os_architecture=$osArch
        last_boot=$lastBoot
        manufacturer=$manufacturer
        model=$model
        memory_bytes=$memoryBytes
        powershell=$PSVersionTable.PSVersion.ToString()
        probe_error=$hostProbeError
        disks=$diskInventory
    }
    bootstrap=[ordered]@{status='NOT_RUN';error=$null}
    cli=[ordered]@{status='NOT_RUN';exit_code=-1;log=$CliLogPath}
    doctor=[ordered]@{status='NOT_RUN';exit_code=-1;log=$DoctorLogPath;evidence_count=0;evidence_files=@()}
    system_events=[ordered]@{status='NOT_RUN';count=0;path=$EventPath;error=$null}
    drivers=[ordered]@{status='NOT_RUN';count=0;path=$DriverPath;error=$null}
    warnings=@()
}

if($elevated){
    $Report.warnings += 'Preflight is running elevated. The preflight remains non-installing, but normal non-elevated execution is preferred for the physical release gate.'
}

try{
    $bootstrap=Join-Path $ProjectRoot 'Bootstrap_SafeCore.ps1'
    if(-not(Test-Path -LiteralPath $bootstrap -PathType Leaf)){throw 'Bootstrap_SafeCore.ps1 missing'}
    & $bootstrap -ProjectRoot $ProjectRoot | Out-File -LiteralPath (Join-Path $RunDir 'bootstrap.log') -Encoding utf8
    foreach($required in @('engine\Core.psm1','engine\EmergencyDoctor.ps1','gui\Workbench.Wpf.ps1')){
        if(-not(Test-Path -LiteralPath (Join-Path $ProjectRoot $required) -PathType Leaf)){throw ('Bootstrap output missing: '+$required)}
    }
    $Report.bootstrap.status='PASS'
}catch{
    $Report.bootstrap.status='FAIL'
    $Report.bootstrap.error=$_.Exception.Message
    Write-PreflightArtifacts -Report $Report
    Write-Host "PHYSICAL_PREFLIGHT=FAIL stage=bootstrap report=$ReportPath"
    exit 2
}

try{
    $launcher=Join-Path $ProjectRoot 'Start_M_LLM_Workbench.ps1'
    $cliArgs=@('-NoProfile','-ExecutionPolicy','Bypass','-File',$launcher,'-Cli','-DataRoot',$DataRoot,'-NetworkMode','OFFLINE_CACHE')
    $cliResult=Invoke-ChildPowerShell -Arguments $cliArgs -LogPath $CliLogPath
    $Report.cli.exit_code=$cliResult.exit_code
    if($cliResult.exit_code -eq 0){$Report.cli.status='PASS'}else{$Report.cli.status='FAIL'}
}catch{
    $Report.cli.status='FAIL'
    $Report.warnings += ('CLI probe exception: '+$_.Exception.Message)
}

if($Report.cli.exit_code -ne 0){
    Write-PreflightArtifacts -Report $Report
    Write-Host "PHYSICAL_PREFLIGHT=FAIL stage=cli report=$ReportPath"
    exit 3
}

try{
    $launcher=Join-Path $ProjectRoot 'Start_M_LLM_Workbench.ps1'
    $doctorArgs=@('-NoProfile','-ExecutionPolicy','Bypass','-File',$launcher,'-Doctor','-DataRoot',$DataRoot,'-NetworkMode','OFFLINE_CACHE')
    $doctorResult=Invoke-ChildPowerShell -Arguments $doctorArgs -LogPath $DoctorLogPath
    $Report.doctor.exit_code=$doctorResult.exit_code
    if($doctorResult.exit_code -in @(0,1)){$Report.doctor.status='COMPLETE'}else{$Report.doctor.status='ERROR'}
    $doctorEvidence=@(Get-ChildItem -LiteralPath (Join-Path $DataRoot 'evidence') -Filter '*.zip' -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending)
    $Report.doctor.evidence_count=$doctorEvidence.Count
    $Report.doctor.evidence_files=@($doctorEvidence | ForEach-Object {$_.FullName})
    if($doctorEvidence.Count -gt 0){
        Copy-Item -LiteralPath $doctorEvidence[0].FullName -Destination (Join-Path $RunDir 'doctor_evidence.zip') -Force
    }
}catch{
    $Report.doctor.status='ERROR'
    $Report.warnings += ('Doctor probe exception: '+$_.Exception.Message)
}

if(-not $SkipEventLog){
    try{
        $since=(Get-Date).AddDays(-7)
        $events=@(Get-WinEvent -FilterHashtable @{LogName='System';StartTime=$since} -MaxEvents 400 -ErrorAction Stop | Where-Object {
            ($_.Id -in @(41,1001,17,18,19,20,46)) -or ($_.ProviderName -match 'WHEA|Kernel-Power|SystemErrorReporting')
        } | Select-Object -First 200 TimeCreated,Id,ProviderName,LevelDisplayName,Message)
        $events | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $EventPath -Encoding UTF8
        $Report.system_events.status='PASS'
        $Report.system_events.count=$events.Count
    }catch{
        $Report.system_events.status='WARN'
        $Report.system_events.error=$_.Exception.Message
    }
}else{
    $Report.system_events.status='SKIPPED'
}

if(-not $SkipDriverInventory){
    try{
        $drivers=@(Get-CimInstance -ClassName Win32_PnPSignedDriver -ErrorAction Stop | Select-Object DeviceName,Manufacturer,DriverProviderName,DriverVersion,DriverDate,InfName,IsSigned)
        $drivers | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $DriverPath -Encoding UTF8
        $Report.drivers.status='PASS'
        $Report.drivers.count=$drivers.Count
    }catch{
        $Report.drivers.status='WARN'
        $Report.drivers.error=$_.Exception.Message
    }
}else{
    $Report.drivers.status='SKIPPED'
}

if($Report.doctor.status -ne 'COMPLETE'){
    $Report.warnings += 'Doctor execution did not complete with the expected diagnostic exit semantics.'
}
if($Report.doctor.evidence_count -lt 1){
    $Report.warnings += 'Doctor did not produce an evidence ZIP.'
}

Write-PreflightArtifacts -Report $Report
try{
    if(Test-Path -LiteralPath $BundlePath -PathType Leaf){Remove-Item -LiteralPath $BundlePath -Force}
    Compress-Archive -LiteralPath (Join-Path $RunDir '*') -DestinationPath $BundlePath -CompressionLevel Optimal -Force
}catch{
    $Report.warnings += ('Evidence bundle creation warning: '+$_.Exception.Message)
    Write-PreflightArtifacts -Report $Report
}

if($Report.doctor.status -ne 'COMPLETE'){
    Write-Host "PHYSICAL_PREFLIGHT=FAIL stage=doctor report=$ReportPath bundle=$BundlePath"
    exit 4
}

Write-Host "PHYSICAL_PREFLIGHT=PASS gate=$($Report.release_gate) core_install_authorized=false report=$ReportPath bundle=$BundlePath"
exit 0
