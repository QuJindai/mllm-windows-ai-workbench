Set-StrictMode -Version 2

function Initialize-MLLMRuntimeCore {
    param([Parameter(Mandatory=$true)][string]$ProjectRoot)
    $root=[IO.Path]::GetFullPath($ProjectRoot)
    foreach($name in @('Core','State','Runtime')){
        $path=Join-Path $root ('engine\'+$name+'.psm1')
        if(Test-Path -LiteralPath $path -PathType Leaf){Import-Module $path -ErrorAction Stop}
    }
}

function Get-MLLMRuntimeConfig {
    param([Parameter(Mandatory=$true)][string]$ProjectRoot)
    Initialize-MLLMRuntimeCore -ProjectRoot $ProjectRoot
    $command=Get-Command Get-MLLMConfig -ErrorAction SilentlyContinue
    if($null -eq $command){throw 'SERVICE_RUNTIME_MISSING|Safe Core configuration runtime is unavailable'}
    return (Get-MLLMConfig -ProjectRoot $ProjectRoot)
}

function Invoke-MLLMLocalModelStartCore {
    param([Parameter(Mandatory=$true)][string]$ProjectRoot,[Parameter(Mandatory=$true)][string]$DataRoot,[Parameter(Mandatory=$true)][string]$ModelPath,[int]$ContextSize=0)
    Initialize-MLLMRuntimeCore -ProjectRoot $ProjectRoot
    if($ContextSize -le 0){
        $config=Get-MLLMRuntimeConfig -ProjectRoot $ProjectRoot
        $api=Get-MLLMPropertyValue -Object $config -Name 'api' -Default $null
        $ContextSize=[int](Get-MLLMPropertyValue -Object $api -Name 'context_size' -Default 8192)
    }
    if($null -eq (Get-Command Start-MLLMLocalModelService -ErrorAction SilentlyContinue)){throw 'SERVICE_RUNTIME_MISSING|Local model runtime is unavailable'}
    try{return (Start-MLLMLocalModelService -DataRoot $DataRoot -ModelPath $ModelPath -ContextSize $ContextSize)}catch{
        $message=[string]$_.Exception.Message
        if($message -match '(?i)not installed|missing|llama|runtime'){throw ('SERVICE_RUNTIME_MISSING|'+$message)}
        throw
    }
}

function Invoke-MLLMLocalModelStopCore {
    param([Parameter(Mandatory=$true)][string]$ProjectRoot,[Parameter(Mandatory=$true)][string]$DataRoot)
    Initialize-MLLMRuntimeCore -ProjectRoot $ProjectRoot
    if($null -eq (Get-Command Stop-MLLMLocalModelService -ErrorAction SilentlyContinue)){throw 'SERVICE_RUNTIME_MISSING|Local model stop runtime is unavailable'}
    return (Stop-MLLMLocalModelService -DataRoot $DataRoot)
}

function Invoke-MLLMWebStartCore {
    param([Parameter(Mandatory=$true)][string]$ProjectRoot,[Parameter(Mandatory=$true)][string]$DataRoot,[Parameter(Mandatory=$true)][string]$NetworkMode)
    Initialize-MLLMRuntimeCore -ProjectRoot $ProjectRoot
    foreach($required in @('Get-MLLMState','Set-MLLMStateValue','Get-MLLMFreePort','Test-MLLMRecordedProcess','Get-MLLMConfig')){
        if($null -eq (Get-Command $required -ErrorAction SilentlyContinue)){throw ('SERVICE_RUNTIME_MISSING|Safe Core command missing: '+$required)}
    }
    $config=Get-MLLMConfig -ProjectRoot $ProjectRoot
    $state=Get-MLLMState -Root $DataRoot
    $runtime=Get-MLLMPropertyValue -Object $state -Name 'runtime' -Default $null
    $webState=Get-MLLMPropertyValue -Object $runtime -Name 'web' -Default $null
    $existingPid=[int](Get-MLLMPropertyValue -Object $webState -Name 'pid' -Default 0)
    if($existingPid -gt 0 -and (Test-MLLMRecordedProcess -ProcessId $existingPid)){
        return [pscustomobject]@{
            pid=$existingPid
            port=Get-MLLMPropertyValue -Object $webState -Name 'port' -Default $null
            base_url=Get-MLLMPropertyValue -Object $webState -Name 'base_url' -Default $null
            stdoutLog=Get-MLLMPropertyValue -Object $webState -Name 'stdout_log' -Default $null
            stderrLog=Get-MLLMPropertyValue -Object $webState -Name 'stderr_log' -Default $null
            already_running=$true
        }
    }

    $webPython=Join-Path ([IO.Path]::GetFullPath($DataRoot)) 'venvs\web\Scripts\python.exe'
    if(-not(Test-Path -LiteralPath $webPython -PathType Leaf)){throw 'SERVICE_RUNTIME_MISSING|Web Workbench runtime not installed'}
    $backend=Join-Path ([IO.Path]::GetFullPath($ProjectRoot)) 'web\backend'
    if(-not(Test-Path -LiteralPath $backend -PathType Container)){throw 'SERVICE_RUNTIME_MISSING|Web Workbench backend is missing'}

    $webConfig=Get-MLLMPropertyValue -Object $config -Name 'web' -Default $null
    $preferred=[int](Get-MLLMPropertyValue -Object $webConfig -Name 'preferred_port' -Default 8765)
    $portMax=[int](Get-MLLMPropertyValue -Object $webConfig -Name 'port_max' -Default 8775)
    $lanEnabled=[bool](Get-MLLMPropertyValue -Object $webState -Name 'lan_enabled' -Default $false)
    $bindHost=if($lanEnabled){'0.0.0.0'}else{'127.0.0.1'}
    $port=Get-MLLMFreePort -BindHost $bindHost -Start $preferred -End $portMax
    $logDir=Join-Path ([IO.Path]::GetFullPath($DataRoot)) 'logs\web'
    New-Item -ItemType Directory -Force -Path $logDir | Out-Null
    $stamp=Get-Date -Format 'yyyyMMdd_HHmmss_fff'
    $out=Join-Path $logDir ('web_'+$stamp+'.out.log')
    $err=Join-Path $logDir ('web_'+$stamp+'.err.log')

    $oldProj=$env:MLLM_PROJECT_ROOT
    $oldData=$env:MLLM_DATA_ROOT
    $env:MLLM_PROJECT_ROOT=$ProjectRoot
    $env:MLLM_DATA_ROOT=$DataRoot
    try{
        $process=Start-Process -FilePath $webPython -ArgumentList @('-m','uvicorn','app:app','--host',$bindHost,'--port',[string]$port) -WorkingDirectory $backend -PassThru -WindowStyle Hidden -RedirectStandardOutput $out -RedirectStandardError $err
    }finally{
        $env:MLLM_PROJECT_ROOT=$oldProj
        $env:MLLM_DATA_ROOT=$oldData
    }

    $base='http://127.0.0.1:'+$port
    Set-MLLMStateValue -Root $DataRoot -Path 'runtime.web.pid' -Value $process.Id | Out-Null
    Set-MLLMStateValue -Root $DataRoot -Path 'runtime.web.port' -Value $port | Out-Null
    Set-MLLMStateValue -Root $DataRoot -Path 'runtime.web.base_url' -Value $base | Out-Null
    Set-MLLMStateValue -Root $DataRoot -Path 'runtime.web.stdout_log' -Value $out | Out-Null
    Set-MLLMStateValue -Root $DataRoot -Path 'runtime.web.stderr_log' -Value $err | Out-Null

    $deadline=(Get-Date).AddSeconds(30)
    do{
        Start-Sleep -Milliseconds 500
        try{
            $response=Invoke-RestMethod ($base+'/api/health') -TimeoutSec 2
            if([bool](Get-MLLMPropertyValue -Object $response -Name 'ok' -Default $false)){
                return [pscustomobject]@{pid=$process.Id;port=$port;base_url=$base;stdoutLog=$out;stderrLog=$err;already_running=$false}
            }
        }catch{}
        if(-not(Test-MLLMRecordedProcess -ProcessId $process.Id)){
            Set-MLLMStateValue -Root $DataRoot -Path 'runtime.web.pid' -Value 0 | Out-Null
            throw 'SERVICE_EXITED_EARLY|Web backend exited before health became ready'
        }
    }while((Get-Date) -lt $deadline)

    try{if(-not $process.HasExited){Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue}}catch{}
    Set-MLLMStateValue -Root $DataRoot -Path 'runtime.web.pid' -Value 0 | Out-Null
    throw 'SERVICE_HEALTH_TIMEOUT|Web backend health timeout'
}

function Invoke-MLLMWebStopCore {
    param([Parameter(Mandatory=$true)][string]$ProjectRoot,[Parameter(Mandatory=$true)][string]$DataRoot)
    Initialize-MLLMRuntimeCore -ProjectRoot $ProjectRoot
    if($null -eq (Get-Command Get-MLLMState -ErrorAction SilentlyContinue)){throw 'SERVICE_RUNTIME_MISSING|Safe Core state runtime is unavailable'}
    $state=Get-MLLMState -Root $DataRoot
    $runtime=Get-MLLMPropertyValue -Object $state -Name 'runtime' -Default $null
    $webState=Get-MLLMPropertyValue -Object $runtime -Name 'web' -Default $null
    $pid=[int](Get-MLLMPropertyValue -Object $webState -Name 'pid' -Default 0)
    if($pid -gt 0 -and (Get-Command Test-MLLMRecordedProcess -ErrorAction SilentlyContinue) -and (Test-MLLMRecordedProcess -ProcessId $pid)){
        Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
    }
    if(Get-Command Set-MLLMStateValue -ErrorAction SilentlyContinue){Set-MLLMStateValue -Root $DataRoot -Path 'runtime.web.pid' -Value 0 | Out-Null}
    return [pscustomobject]@{stopped=$true;pid=$pid}
}

function Get-MLLMServiceResultValue {
    param($Result,[Parameter(Mandatory=$true)][string[]]$Names,$Default=$null)
    foreach($name in $Names){
        $value=Get-MLLMPropertyValue -Object $Result -Name $name -Default $null
        if($null -ne $value -and -not([string]::IsNullOrWhiteSpace([string]$value))){return $value}
    }
    return $Default
}

function Resolve-MLLMServiceModel {
    param([Parameter(Mandatory=$true)][string]$ProjectRoot,[Parameter(Mandatory=$true)][string]$DataRoot)
    $active=Get-MLLMActiveModel -DataRoot $DataRoot
    $modelId=[string](Get-MLLMPropertyValue -Object $active -Name 'modelId' -Default '')
    if(-not $modelId){
        $definition=@(Get-MLLMModelCatalog -ProjectRoot $ProjectRoot | Where-Object {[string]$_.role -eq 'local-fast'} | Select-Object -First 1)
        if($definition.Count -eq 0){throw 'SERVICE_MODEL_UNAVAILABLE|No local-fast model is configured'}
        $modelId=[string]$definition[0].id
    }
    $model=Test-MLLMWorkbenchModel -ProjectRoot $ProjectRoot -DataRoot $DataRoot -ModelId $modelId
    if([string]$model.integrityState -in @('Missing','Failed','Unknown')){throw ('SERVICE_MODEL_UNAVAILABLE|'+$modelId+'|'+[string]$model.activationBlockedReason)}
    return $model
}

function Write-MLLMServiceRuntimeRecord {
    param([Parameter(Mandatory=$true)][string]$DataRoot,[Parameter(Mandatory=$true)][string]$ServiceId,[Parameter(Mandatory=$true)][string]$State,$Result,$Model=$null,[string]$HealthSummary='')
    $existing=Get-MLLMServiceRecord -DataRoot $DataRoot -ServiceId $ServiceId
    $pid=[int](Get-MLLMServiceResultValue -Result $Result -Names @('pid','processId','process_id') -Default 0)
    $port=Get-MLLMServiceResultValue -Result $Result -Names @('port') -Default (Get-MLLMPropertyValue -Object $existing -Name 'port' -Default $null)
    $baseUrl=Get-MLLMServiceResultValue -Result $Result -Names @('baseUrl','base_url','url') -Default (Get-MLLMPropertyValue -Object $existing -Name 'baseUrl' -Default $null)
    $stdout=Get-MLLMServiceResultValue -Result $Result -Names @('stdoutLog','stdout_log','outLog','out_log') -Default (Get-MLLMPropertyValue -Object $existing -Name 'stdoutLog' -Default $null)
    $stderr=Get-MLLMServiceResultValue -Result $Result -Names @('stderrLog','stderr_log','errLog','err_log') -Default (Get-MLLMPropertyValue -Object $existing -Name 'stderrLog' -Default $null)
    $record=[ordered]@{
        schema='mllm.service.v1'
        serviceId=$ServiceId
        state=$State
        pid=if($State -eq 'Stopped'){0}else{$pid}
        port=$port
        baseUrl=$baseUrl
        startedAt=if($State -eq 'Stopped'){Get-MLLMPropertyValue -Object $existing -Name 'startedAt' -Default $null}else{(Get-Date).ToString('o')}
        modelId=if($null -ne $Model){[string]$Model.id}else{Get-MLLMPropertyValue -Object $existing -Name 'modelId' -Default $null}
        modelPath=if($null -ne $Model){[string]$Model.filePath}else{Get-MLLMPropertyValue -Object $existing -Name 'modelPath' -Default $null}
        stdoutLog=$stdout
        stderrLog=$stderr
        healthSummary=if($HealthSummary){$HealthSummary}elseif($State -eq 'Stopped'){'Not running.'}else{'Running.'}
        updatedAt=(Get-Date).ToString('o')
    }
    Write-MLLMJsonAtomic -Path (Get-MLLMServiceRecordPath -DataRoot $DataRoot -ServiceId $ServiceId) -Value $record | Out-Null
    return $record
}

function Get-MLLMSelectedServiceSnapshot {
    param([Parameter(Mandatory=$true)][string]$ProjectRoot,[Parameter(Mandatory=$true)][string]$DataRoot,[Parameter(Mandatory=$true)][string]$NetworkMode,[Parameter(Mandatory=$true)][string]$ServiceId)
    return @(Get-MLLMWorkbenchServices -ProjectRoot $ProjectRoot -DataRoot $DataRoot -NetworkMode $NetworkMode | Where-Object {[string]$_.serviceId -eq $ServiceId})[0]
}

function Start-MLLMWorkbenchService {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)][ValidateNotNullOrEmpty()][string]$ProjectRoot,
        [Parameter(Mandatory=$true)][ValidateNotNullOrEmpty()][string]$DataRoot,
        [Parameter(Mandatory=$true)][ValidateSet('AUTO_CN_FIRST','CHINA_ONLY','GLOBAL_FIRST','OFFLINE_CACHE','CUSTOM_PROXY')][string]$NetworkMode,
        [Parameter(Mandatory=$true)][ValidateNotNullOrEmpty()][string]$ServiceId
    )
    if(-not(Test-MLLMManagedServiceId -ServiceId $ServiceId)){throw ('SERVICE_NOT_FOUND|'+$ServiceId)}
    $current=Get-MLLMSelectedServiceSnapshot -ProjectRoot $ProjectRoot -DataRoot $DataRoot -NetworkMode $NetworkMode -ServiceId $ServiceId
    if([bool]$current.canStop){throw ('SERVICE_ALREADY_RUNNING|'+$ServiceId)}

    if($ServiceId -eq 'local-model-api'){
        $model=Resolve-MLLMServiceModel -ProjectRoot $ProjectRoot -DataRoot $DataRoot
        $result=Invoke-MLLMLocalModelStartCore -ProjectRoot $ProjectRoot -DataRoot $DataRoot -ModelPath ([string]$model.filePath)
        $pid=[int](Get-MLLMServiceResultValue -Result $result -Names @('pid','processId','process_id') -Default 0)
        if($pid -le 0){throw 'SERVICE_EXITED_EARLY|Local model service did not return an owned process id'}
        Write-MLLMServiceRuntimeRecord -DataRoot $DataRoot -ServiceId $ServiceId -State 'Running' -Result $result -Model $model -HealthSummary 'Local model service running.' | Out-Null
    }else{
        $result=Invoke-MLLMWebStartCore -ProjectRoot $ProjectRoot -DataRoot $DataRoot -NetworkMode $NetworkMode
        $pid=[int](Get-MLLMServiceResultValue -Result $result -Names @('pid','processId','process_id') -Default 0)
        if($pid -le 0){throw 'SERVICE_EXITED_EARLY|Web Workbench did not return an owned process id'}
        Write-MLLMServiceRuntimeRecord -DataRoot $DataRoot -ServiceId $ServiceId -State 'Running' -Result $result -HealthSummary 'Web Workbench running.' | Out-Null
    }
    return (Get-MLLMSelectedServiceSnapshot -ProjectRoot $ProjectRoot -DataRoot $DataRoot -NetworkMode $NetworkMode -ServiceId $ServiceId)
}

function Stop-MLLMWorkbenchService {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)][ValidateNotNullOrEmpty()][string]$ProjectRoot,
        [Parameter(Mandatory=$true)][ValidateNotNullOrEmpty()][string]$DataRoot,
        [Parameter(Mandatory=$true)][ValidateNotNullOrEmpty()][string]$ServiceId
    )
    if(-not(Test-MLLMManagedServiceId -ServiceId $ServiceId)){throw ('SERVICE_NOT_FOUND|'+$ServiceId)}
    $record=Get-MLLMServiceRecord -DataRoot $DataRoot -ServiceId $ServiceId
    if($null -eq $record){throw ('SERVICE_NOT_RUNNING|'+$ServiceId)}
    $pid=[int](Get-MLLMPropertyValue -Object $record -Name 'pid' -Default 0)
    $recordedState=[string](Get-MLLMPropertyValue -Object $record -Name 'state' -Default 'Stopped')
    if($pid -le 0 -or $recordedState -eq 'Stopped'){throw ('SERVICE_NOT_RUNNING|'+$ServiceId)}
    if(-not(Test-MLLMServiceProcessOwned -ProjectRoot $ProjectRoot -ProcessId $pid)){throw ('SERVICE_PROCESS_OWNERSHIP_FAILED|'+$ServiceId+'|'+$pid)}

    if($ServiceId -eq 'local-model-api'){$result=Invoke-MLLMLocalModelStopCore -ProjectRoot $ProjectRoot -DataRoot $DataRoot}
    else{$result=Invoke-MLLMWebStopCore -ProjectRoot $ProjectRoot -DataRoot $DataRoot}
    Write-MLLMServiceRuntimeRecord -DataRoot $DataRoot -ServiceId $ServiceId -State 'Stopped' -Result $result -HealthSummary 'Not running.' | Out-Null
    return (Convert-MLLMServiceRecord -ProjectRoot $ProjectRoot -DataRoot $DataRoot -NetworkMode 'OFFLINE_CACHE' -ServiceId $ServiceId -Record (Get-MLLMServiceRecord -DataRoot $DataRoot -ServiceId $ServiceId))
}

function Restart-MLLMWorkbenchService {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)][ValidateNotNullOrEmpty()][string]$ProjectRoot,
        [Parameter(Mandatory=$true)][ValidateNotNullOrEmpty()][string]$DataRoot,
        [Parameter(Mandatory=$true)][ValidateSet('AUTO_CN_FIRST','CHINA_ONLY','GLOBAL_FIRST','OFFLINE_CACHE','CUSTOM_PROXY')][string]$NetworkMode,
        [Parameter(Mandatory=$true)][ValidateNotNullOrEmpty()][string]$ServiceId
    )
    Stop-MLLMWorkbenchService -ProjectRoot $ProjectRoot -DataRoot $DataRoot -ServiceId $ServiceId | Out-Null
    $stopped=Get-MLLMSelectedServiceSnapshot -ProjectRoot $ProjectRoot -DataRoot $DataRoot -NetworkMode $NetworkMode -ServiceId $ServiceId
    if([string]$stopped.state -ne 'Stopped'){throw ('SERVICE_PROCESS_OWNERSHIP_FAILED|'+$ServiceId+' did not stop cleanly')}
    return (Start-MLLMWorkbenchService -ProjectRoot $ProjectRoot -DataRoot $DataRoot -NetworkMode $NetworkMode -ServiceId $ServiceId)
}
