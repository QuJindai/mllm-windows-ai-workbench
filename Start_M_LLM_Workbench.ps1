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
$config=Get-MLLMConfig -ProjectRoot $ProjectRoot
if(-not $DataRoot){$DataRoot=Select-MLLMRoot -Config $config}
Initialize-MLLMStateStore -Root $DataRoot|Out-Null
Import-MLLMTasks -ProjectRoot $ProjectRoot
$runDir=Start-MLLMRunLog -Root $DataRoot
$profile=Get-MLLMSystemProfile;$profile|ConvertTo-Json -Depth 10|Set-Content (Join-Path $runDir 'system.json') -Encoding UTF8
"M-LLM Workbench start $(Get-Date -Format o) project=$ProjectRoot data=$DataRoot mode=$NetworkMode"|Set-Content (Join-Path $runDir 'bootstrap.log') -Encoding UTF8

function Get-LocalFastModelPath {
    $manifest=(Get-Content (Join-Path $ProjectRoot 'config\models.json') -Raw|ConvertFrom-Json).models|Where-Object {$_.role -eq 'local-fast'}|Select-Object -First 1
    Join-Path $DataRoot ('models\Qwen3.5-4B\'+$manifest.canonical_filename)
}
function Start-WorkbenchWeb {
    $state=Get-MLLMState -Root $DataRoot
    if($state.runtime -and $state.runtime.web -and $state.runtime.web.pid -and (Test-MLLMRecordedProcess -ProcessId ([int]$state.runtime.web.pid))){return [pscustomobject]@{pid=$state.runtime.web.pid;base_url=$state.runtime.web.base_url;already_running=$true}}
    $webPython=Join-Path $DataRoot 'venvs\web\Scripts\python.exe';if(-not(Test-Path $webPython)){throw 'Web Workbench runtime not installed. Run Web Workbench preset first.'}
    $bindHost=if($state.runtime.web.lan_enabled -eq $true){'0.0.0.0'}else{'127.0.0.1'};$port=Get-MLLMFreePort -BindHost $bindHost -Start ([int]$config.web.preferred_port) -End ([int]$config.web.port_max);$backend=Join-Path $ProjectRoot 'web\backend';$logDir=Join-Path $DataRoot 'logs\web';New-Item -ItemType Directory -Path $logDir -Force|Out-Null;$stamp=Get-Date -Format 'yyyyMMdd_HHmmss_fff';$out=Join-Path $logDir "web_$stamp.out.log";$err=Join-Path $logDir "web_$stamp.err.log"
    $oldProj=$env:MLLM_PROJECT_ROOT;$oldData=$env:MLLM_DATA_ROOT;$env:MLLM_PROJECT_ROOT=$ProjectRoot;$env:MLLM_DATA_ROOT=$DataRoot
    try{$p=Start-Process -FilePath $webPython -ArgumentList @('-m','uvicorn','app:app','--host',$bindHost,'--port',[string]$port) -WorkingDirectory $backend -PassThru -WindowStyle Hidden -RedirectStandardOutput $out -RedirectStandardError $err}finally{$env:MLLM_PROJECT_ROOT=$oldProj;$env:MLLM_DATA_ROOT=$oldData}
    $base="http://127.0.0.1`:$port";Set-MLLMStateValue -Root $DataRoot -Path 'runtime.web.pid' -Value $p.Id|Out-Null;Set-MLLMStateValue -Root $DataRoot -Path 'runtime.web.port' -Value $port|Out-Null;Set-MLLMStateValue -Root $DataRoot -Path 'runtime.web.base_url' -Value $base|Out-Null
    $deadline=(Get-Date).AddSeconds(30);do{Start-Sleep -Milliseconds 500;try{$r=Invoke-RestMethod "$base/api/health" -TimeoutSec 2;if($r.ok){return [pscustomobject]@{pid=$p.Id;base_url=$base;port=$port}}}catch{};if(-not(Test-MLLMRecordedProcess -ProcessId $p.Id)){throw 'Web backend exited before health became ready'}}while((Get-Date)-lt $deadline);throw 'Web backend health timeout'
}
function Stop-WorkbenchWeb {
    $state=Get-MLLMState -Root $DataRoot;$processId=0;if($state.runtime -and $state.runtime.web -and $state.runtime.web.pid){$processId=[int]$state.runtime.web.pid};if($processId -gt 0 -and (Test-MLLMRecordedProcess -ProcessId $processId)){Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue};Set-MLLMStateValue -Root $DataRoot -Path 'runtime.web.pid' -Value 0|Out-Null;[pscustomobject]@{stopped=$true;pid=$processId}
}

try{
    if($Preset){$results=Invoke-MLLMPreset -Preset $Preset -ProjectRoot $ProjectRoot -DataRoot $DataRoot -NetworkMode $NetworkMode -RunDir $runDir -OnProgress {param($x)Write-Host "[M-LLM] $x"};$results|ConvertTo-Json -Depth 20|Set-Content (Join-Path $runDir 'summary.json') -Encoding UTF8;$results|Format-Table id,status,summary -AutoSize;if($Cli){exit ([int](@($results|Where-Object {$_.status -in @('FAILED','BLOCKED')}).Count -gt 0))}}
    if($StartService){$model=Get-LocalFastModelPath;$svc=Start-MLLMLocalModelService -DataRoot $DataRoot -ModelPath $model -ContextSize ([int]$config.api.context_size);$svc|ConvertTo-Json -Depth 10;exit 0}
    if($StopService){Stop-MLLMLocalModelService -DataRoot $DataRoot|ConvertTo-Json;exit 0}
    if($StartWeb){Start-WorkbenchWeb|ConvertTo-Json;exit 0}
    if($StopWeb){Stop-WorkbenchWeb|ConvertTo-Json;exit 0}
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
