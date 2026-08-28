[CmdletBinding()]
param()

$ErrorActionPreference='Stop'
Set-StrictMode -Version 2
$root=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$modulePath=Join-Path $root 'runtime\WorkbenchRuntimeAdapter.psm1'
if(-not(Test-Path -LiteralPath $modulePath -PathType Leaf)){throw "WorkbenchRuntimeAdapter.psm1 missing: $modulePath"}
Import-Module $modulePath -Force -ErrorAction Stop

foreach($commandName in @('Start-MLLMWorkbenchService','Stop-MLLMWorkbenchService','Restart-MLLMWorkbenchService')){
    if($null -eq (Get-Command $commandName -ErrorAction SilentlyContinue)){throw "Runtime adapter lifecycle command missing: $commandName"}
}

function Assert-ThrowsCode {
    param([scriptblock]$Action,[string]$Code)
    $threw=$false
    try{& $Action}catch{
        $threw=$true
        if($_.Exception.Message -notmatch [regex]::Escape($Code)){throw "Expected error code $Code, got: $($_.Exception.Message)"}
    }
    if(-not $threw){throw "Expected operation to throw $Code"}
}

$testRoot=Join-Path $env:RUNNER_TEMP ('mllm phase b lifecycle '+[guid]::NewGuid().ToString('N'))
$project=Join-Path $testRoot 'project'
$data=Join-Path $testRoot 'data'
$configDir=Join-Path $project 'config'
$engineDir=Join-Path $project 'engine'
$modelDir=Join-Path $data 'models\Qwen3.5-4B'
$logsDir=Join-Path $data 'logs\runtime'
$stateDir=Join-Path $data 'state\services'
New-Item -ItemType Directory -Force -Path $configDir,$engineDir,$modelDir,$logsDir,$stateDir | Out-Null

@'
function Test-MLLMRecordedProcess {
    param([int]$ProcessId)
    return ($ProcessId -eq $PID)
}
Export-ModuleMember -Function Test-MLLMRecordedProcess
'@ | Set-Content -LiteralPath (Join-Path $engineDir 'Runtime.psm1') -Encoding ASCII

$manifest=[ordered]@{models=@([ordered]@{id='fixture-local';role='local-fast';repository='fixture/local';allow_patterns=@('*.gguf');canonical_filename='fixture.gguf';filename_candidates=@('fixture.gguf');format='gguf';minimum_bytes=4;sha256=$null})}
$manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $configDir 'models.json') -Encoding UTF8
[IO.File]::WriteAllBytes((Join-Path $modelDir 'fixture.gguf'),[Text.Encoding]::ASCII.GetBytes('GGUFfixture'))

$stdout=Join-Path $logsDir 'fixture.out.log'
$stderr=Join-Path $logsDir 'fixture.err.log'
'fixture out' | Set-Content -LiteralPath $stdout -Encoding UTF8
'fixture err' | Set-Content -LiteralPath $stderr -Encoding UTF8

$adapter=Get-Module WorkbenchRuntimeAdapter -ErrorAction Stop
& $adapter {
    $script:LifecycleCalls=New-Object Collections.Generic.List[string]
    $script:LocalStartMode='ok'
    $script:WebStartMode='ok'
    $script:FixtureStdout=$null
    $script:FixtureStderr=$null

    Set-Item -Path Function:script:Invoke-MLLMLocalModelStartCore -Force -Value {
        param([string]$ProjectRoot,[string]$DataRoot,[string]$ModelPath,[int]$ContextSize=0)
        $script:LifecycleCalls.Add('local-start')
        if($script:LocalStartMode -eq 'missing'){throw 'SERVICE_RUNTIME_MISSING|llama.cpp runtime missing'}
        return [pscustomobject]@{pid=$PID;port=8123;base_url='http://127.0.0.1:8123';stdoutLog=$script:FixtureStdout;stderrLog=$script:FixtureStderr}
    }
    Set-Item -Path Function:script:Invoke-MLLMLocalModelStopCore -Force -Value {
        param([string]$ProjectRoot,[string]$DataRoot)
        $script:LifecycleCalls.Add('local-stop')
        return [pscustomobject]@{stopped=$true}
    }
    Set-Item -Path Function:script:Invoke-MLLMWebStartCore -Force -Value {
        param([string]$ProjectRoot,[string]$DataRoot,[string]$NetworkMode)
        $script:LifecycleCalls.Add('web-start')
        if($script:WebStartMode -eq 'early'){throw 'SERVICE_EXITED_EARLY|web fixture exited'}
        if($script:WebStartMode -eq 'timeout'){throw 'SERVICE_HEALTH_TIMEOUT|web fixture health timeout'}
        return [pscustomobject]@{pid=$PID;port=8765;base_url='http://127.0.0.1:8765';stdoutLog=$script:FixtureStdout;stderrLog=$script:FixtureStderr}
    }
    Set-Item -Path Function:script:Invoke-MLLMWebStopCore -Force -Value {
        param([string]$ProjectRoot,[string]$DataRoot)
        $script:LifecycleCalls.Add('web-stop')
        return [pscustomobject]@{stopped=$true}
    }
}
& $adapter { param($Out,$Err) $script:FixtureStdout=$Out;$script:FixtureStderr=$Err } $stdout $stderr

function Set-AdapterMode {
    param([string]$Local='ok',[string]$Web='ok')
    & $adapter { param($L,$W) $script:LocalStartMode=$L;$script:WebStartMode=$W } $Local $Web
}
function Clear-Calls { & $adapter { $script:LifecycleCalls.Clear() } }
function Get-Calls { return @(& $adapter { $script:LifecycleCalls.ToArray() }) }
function Remove-ServiceRecord { param([string]$Id) Remove-Item -LiteralPath (Join-Path $stateDir ($Id+'.json')) -Force -ErrorAction SilentlyContinue }

try{
    Assert-ThrowsCode -Code 'SERVICE_NOT_FOUND' -Action { Start-MLLMWorkbenchService -ProjectRoot $project -DataRoot $data -NetworkMode OFFLINE_CACHE -ServiceId 'arbitrary-service' | Out-Null }
    Assert-ThrowsCode -Code 'SERVICE_NOT_RUNNING' -Action { Stop-MLLMWorkbenchService -ProjectRoot $project -DataRoot $data -ServiceId 'web-workbench' | Out-Null }

    Set-AdapterMode -Local ok -Web ok
    Clear-Calls
    $started=Start-MLLMWorkbenchService -ProjectRoot $project -DataRoot $data -NetworkMode OFFLINE_CACHE -ServiceId 'local-model-api'
    if([string]$started.state -ne 'Running' -or [int]$started.pid -ne $PID){throw "Local service did not reach Running: $($started|ConvertTo-Json -Compress)"}
    if([string]$started.modelId -ne 'fixture-local'){throw "Local service did not use built-in fallback model: $($started.modelId)"}
    if((Get-Calls) -join '|' -ne 'local-start'){throw "Unexpected local start call sequence: $((Get-Calls)-join '|')"}
    Assert-ThrowsCode -Code 'SERVICE_ALREADY_RUNNING' -Action { Start-MLLMWorkbenchService -ProjectRoot $project -DataRoot $data -NetworkMode OFFLINE_CACHE -ServiceId 'local-model-api' | Out-Null }

    Clear-Calls
    $stopped=Stop-MLLMWorkbenchService -ProjectRoot $project -DataRoot $data -ServiceId 'local-model-api'
    if([string]$stopped.state -ne 'Stopped'){throw "Local stop did not reconstruct Stopped: $($stopped.state)"}
    if((Get-Calls) -join '|' -ne 'local-stop'){throw "Unexpected local stop sequence: $((Get-Calls)-join '|')"}

    Start-MLLMWorkbenchService -ProjectRoot $project -DataRoot $data -NetworkMode OFFLINE_CACHE -ServiceId 'local-model-api' | Out-Null
    Clear-Calls
    $restarted=Restart-MLLMWorkbenchService -ProjectRoot $project -DataRoot $data -NetworkMode OFFLINE_CACHE -ServiceId 'local-model-api'
    if([string]$restarted.state -ne 'Running'){throw 'Restart did not return Running'}
    if((Get-Calls) -join '|' -ne 'local-stop|local-start'){throw "Restart ordering mismatch: $((Get-Calls)-join '|')"}
    Stop-MLLMWorkbenchService -ProjectRoot $project -DataRoot $data -ServiceId 'local-model-api' | Out-Null

    Set-AdapterMode -Local missing -Web ok
    Remove-ServiceRecord -Id 'local-model-api'
    Assert-ThrowsCode -Code 'SERVICE_RUNTIME_MISSING' -Action { Start-MLLMWorkbenchService -ProjectRoot $project -DataRoot $data -NetworkMode OFFLINE_CACHE -ServiceId 'local-model-api' | Out-Null }
    $afterMissing=@(Get-MLLMWorkbenchServices -ProjectRoot $project -DataRoot $data -NetworkMode OFFLINE_CACHE | Where-Object {$_.serviceId -eq 'local-model-api'})[0]
    if([string]$afterMissing.state -ne 'Stopped'){throw 'Missing runtime changed local service into running state'}

    Set-AdapterMode -Local ok -Web early
    Remove-ServiceRecord -Id 'web-workbench'
    Assert-ThrowsCode -Code 'SERVICE_EXITED_EARLY' -Action { Start-MLLMWorkbenchService -ProjectRoot $project -DataRoot $data -NetworkMode OFFLINE_CACHE -ServiceId 'web-workbench' | Out-Null }
    Set-AdapterMode -Local ok -Web timeout
    Assert-ThrowsCode -Code 'SERVICE_HEALTH_TIMEOUT' -Action { Start-MLLMWorkbenchService -ProjectRoot $project -DataRoot $data -NetworkMode OFFLINE_CACHE -ServiceId 'web-workbench' | Out-Null }

    Set-AdapterMode -Local ok -Web ok
    $web=Start-MLLMWorkbenchService -ProjectRoot $project -DataRoot $data -NetworkMode OFFLINE_CACHE -ServiceId 'web-workbench'
    if([string]$web.state -ne 'Running'){throw 'Web service did not reach Running'}
    Stop-MLLMWorkbenchService -ProjectRoot $project -DataRoot $data -ServiceId 'web-workbench' | Out-Null

    $stale=[ordered]@{serviceId='local-model-api';state='Running';pid=2147483000;port=8123;baseUrl='http://127.0.0.1:8123';startedAt=(Get-Date).ToString('o');modelId='fixture-local';modelPath=(Join-Path $modelDir 'fixture.gguf');stdoutLog=$stdout;stderrLog=$stderr;healthSummary='fixture'}
    $stale | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $stateDir 'local-model-api.json') -Encoding UTF8
    Assert-ThrowsCode -Code 'SERVICE_PROCESS_OWNERSHIP_FAILED' -Action { Stop-MLLMWorkbenchService -ProjectRoot $project -DataRoot $data -ServiceId 'local-model-api' | Out-Null }

    $legacy=Get-Content -LiteralPath (Join-Path $root 'Start_M_LLM_Workbench.ps1') -Raw
    if($legacy -match 'function\s+Start-WorkbenchWeb'){throw 'Legacy entrypoint still owns a duplicate Start-WorkbenchWeb implementation'}
    if($legacy -match 'function\s+Stop-WorkbenchWeb'){throw 'Legacy entrypoint still owns a duplicate Stop-WorkbenchWeb implementation'}
    if($legacy -notmatch 'WorkbenchRuntimeAdapter\.psm1'){throw 'Legacy entrypoint does not load shared Runtime Adapter'}
    foreach($id in @('local-model-api','web-workbench')){if($legacy -notmatch [regex]::Escape($id)){throw "Legacy entrypoint does not route service id: $id"}}

    Write-Host 'PHASE_B_SERVICE_LIFECYCLE=PASS ids=PASS start_stop=PASS restart=PASS missing_runtime=PASS early_exit=PASS health_timeout=PASS ownership=PASS legacy_shared=PASS offline=PASS'
}finally{
    Remove-Item -LiteralPath $testRoot -Recurse -Force -ErrorAction SilentlyContinue
}
