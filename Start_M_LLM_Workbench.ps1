[CmdletBinding()]
param(
    [switch]$Cli,
    [switch]$Doctor,
    [switch]$Gui,
    [string]$Preset='',
    [switch]$StartService,
    [switch]$StopService,
    [switch]$StartWeb,
    [switch]$StopWeb,
    [ValidateSet('AUTO_CN_FIRST','CHINA_ONLY','GLOBAL_FIRST','OFFLINE_CACHE','CUSTOM_PROXY')][string]$NetworkMode='AUTO_CN_FIRST',
    [string]$DataRoot=''
)
$ErrorActionPreference='Stop'
$ProjectRoot=$PSScriptRoot
$bootstrapScript=Join-Path $ProjectRoot 'Bootstrap_SafeCore.ps1'
if(Test-Path -LiteralPath $bootstrapScript -PathType Leaf){
    & $bootstrapScript -ProjectRoot $ProjectRoot
}elseif(-not(Test-Path -LiteralPath (Join-Path $ProjectRoot 'engine\Core.psm1') -PathType Leaf)){
    throw 'Safe Core source is not materialized and Bootstrap_SafeCore.ps1 is missing.'
}
foreach($m in @('Core','State','Detection','Network','Download','Security','Evidence','Runtime')){Import-Module (Join-Path $ProjectRoot "engine\$m.psm1") -Force}
$runtimeAdapter=Join-Path $ProjectRoot 'runtime\WorkbenchRuntimeAdapter.psm1'
if(-not(Test-Path -LiteralPath $runtimeAdapter -PathType Leaf)){throw 'WorkbenchRuntimeAdapter.psm1 is missing.'}
Import-Module $runtimeAdapter -Force -ErrorAction Stop
$config=Get-MLLMConfig -ProjectRoot $ProjectRoot
if(-not $DataRoot){$DataRoot=Select-MLLMRoot -Config $config}
Initialize-MLLMStateStore -Root $DataRoot|Out-Null
Import-MLLMTasks -ProjectRoot $ProjectRoot
$runDir=Start-MLLMRunLog -Root $DataRoot
$profile=Get-MLLMSystemProfile;$profile|ConvertTo-Json -Depth 10|Set-Content (Join-Path $runDir 'system.json') -Encoding UTF8
"M-LLM Workbench start $(Get-Date -Format o) project=$ProjectRoot data=$DataRoot mode=$NetworkMode"|Set-Content (Join-Path $runDir 'bootstrap.log') -Encoding UTF8

try{
    if($Preset){$results=Invoke-MLLMPreset -Preset $Preset -ProjectRoot $ProjectRoot -DataRoot $DataRoot -NetworkMode $NetworkMode -RunDir $runDir -OnProgress {param($x)Write-Host "[M-LLM] $x"};$results|ConvertTo-Json -Depth 20|Set-Content (Join-Path $runDir 'summary.json') -Encoding UTF8;$results|Format-Table id,status,summary -AutoSize;if($Cli){exit ([int](@($results|Where-Object {$_.status -in @('FAILED','BLOCKED')}).Count -gt 0))}}
    if($StartService){Start-MLLMWorkbenchService -ProjectRoot $ProjectRoot -DataRoot $DataRoot -NetworkMode $NetworkMode -ServiceId 'local-model-api'|ConvertTo-Json -Depth 10;exit 0}
    if($StopService){Stop-MLLMWorkbenchService -ProjectRoot $ProjectRoot -DataRoot $DataRoot -ServiceId 'local-model-api'|ConvertTo-Json -Depth 10;exit 0}
    if($StartWeb){Start-MLLMWorkbenchService -ProjectRoot $ProjectRoot -DataRoot $DataRoot -NetworkMode $NetworkMode -ServiceId 'web-workbench'|ConvertTo-Json -Depth 10;exit 0}
    if($StopWeb){Stop-MLLMWorkbenchService -ProjectRoot $ProjectRoot -DataRoot $DataRoot -ServiceId 'web-workbench'|ConvertTo-Json -Depth 10;exit 0}
    if($Doctor){$results=Invoke-MLLMDoctor -ProjectRoot $ProjectRoot -DataRoot $DataRoot -NetworkMode $NetworkMode;$results|ConvertTo-Json -Depth 20|Set-Content (Join-Path $runDir 'summary.json') -Encoding UTF8;$results|Format-Table id,status,summary -AutoSize;$zip=Export-MLLMEvidence -Root $DataRoot -RunDir $runDir;Write-Host "EVIDENCE=$zip";exit ([int](@($results|Where-Object {$_.status -eq 'FAILED'}).Count -gt 0))}
    if($Cli){Write-Host "M-LLM data root: $DataRoot";Write-Host "Network mode: $NetworkMode";Get-MLLMRegisteredTasks|Select-Object Id,Name,Dependencies|Format-Table -AutoSize;exit 0}
    try{
        & (Join-Path $ProjectRoot 'gui\Workbench.Wpf.ps1') -ProjectRoot $ProjectRoot -DataRoot $DataRoot -NetworkMode $NetworkMode
    }catch{
        $wpfMessage=$_.Exception.ToString()
        "WPF startup failed $(Get-Date -Format o): $wpfMessage"|Add-Content (Join-Path $runDir 'bootstrap.log') -Encoding UTF8
        Write-Warning 'Native WPF GUI could not start. Switching to diagnostic CLI fallback.'
        Write-Host 'WPF_FALLBACK=CLI'
        try{
            . (Join-Path $ProjectRoot 'engine\EmergencyDoctor.ps1')
            $emergency=Invoke-MLLMEmergencyDoctor -ProjectRoot $ProjectRoot -DataRoot $DataRoot -Cause $wpfMessage
            $emergency.checks|Format-Table id,status,summary -AutoSize
            Write-Host "EVIDENCE=$($emergency.evidence_dir)"
            Write-Host 'Rerun the bootstrap after repair, or send the emergency evidence directory for diagnosis.'
        }catch{
            Write-Warning ("Emergency Doctor also failed: "+$_.Exception.Message)
        }
        exit 2
    }
}catch{
    $msg=$_.Exception.ToString();$msg|Add-Content (Join-Path $runDir 'bootstrap.log') -Encoding UTF8;Write-Error $msg;try{$zip=Export-MLLMEvidence -Root $DataRoot -RunDir $runDir;Write-Host "EVIDENCE=$zip"}catch{};exit 1
}
