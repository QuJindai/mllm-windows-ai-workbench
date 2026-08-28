[CmdletBinding()]
param()

$ErrorActionPreference='Stop'
Set-StrictMode -Version 2
$root=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$module=Join-Path $root 'runtime\WorkbenchRuntimeAdapter.psm1'
if(-not(Test-Path -LiteralPath $module -PathType Leaf)){throw "WorkbenchRuntimeAdapter.psm1 missing: $module"}
Import-Module $module -Force -ErrorAction Stop

foreach($commandName in @('Get-MLLMWorkbenchServices','Get-MLLMWorkbenchServiceLogs')){
    if($null -eq (Get-Command $commandName -ErrorAction SilentlyContinue)){throw "Runtime adapter service command missing: $commandName"}
}

$testRoot=Join-Path $env:RUNNER_TEMP ('mllm phase b service adapter '+[guid]::NewGuid().ToString('N'))
$project=Join-Path $testRoot 'project'
$data=Join-Path $testRoot 'data'
$engineDir=Join-Path $project 'engine'
$stateDir=Join-Path $data 'state\services'
$logsDir=Join-Path $data 'logs\runtime'
New-Item -ItemType Directory -Force -Path $engineDir,$stateDir,$logsDir | Out-Null

@'
function Test-MLLMRecordedProcess {
    param([int]$ProcessId)
    return ($ProcessId -eq $PID)
}
Export-ModuleMember -Function Test-MLLMRecordedProcess
'@ | Set-Content -LiteralPath (Join-Path $engineDir 'Runtime.psm1') -Encoding ASCII

function Write-ServiceRecord {
    param([string]$ServiceId,[int]$ProcessId,[string]$State='Running',[string]$Stdout='',[string]$Stderr='')
    $record=[ordered]@{
        serviceId=$ServiceId
        state=$State
        pid=$ProcessId
        port=8123
        baseUrl='http://127.0.0.1:8123'
        startedAt=(Get-Date).AddSeconds(-15).ToString('o')
        modelId=if($ServiceId -eq 'local-model-api'){'fixture-model'}else{$null}
        modelPath=if($ServiceId -eq 'local-model-api'){Join-Path $data 'models\fixture.gguf'}else{$null}
        stdoutLog=$Stdout
        stderrLog=$Stderr
        healthSummary='fixture'
    }
    $record | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $stateDir ($ServiceId+'.json')) -Encoding UTF8
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

try{
    $empty=@(Get-MLLMWorkbenchServices -ProjectRoot $project -DataRoot $data -NetworkMode 'OFFLINE_CACHE')
    if($empty.Count -ne 2){throw "Expected exactly two managed services, got $($empty.Count)"}
    $ids=@($empty | ForEach-Object {[string]$_.serviceId})
    if(($ids -join '|') -ne 'local-model-api|web-workbench'){throw "Unexpected service ids/order: $($ids -join ',')"}
    foreach($row in $empty){
        if([string]$row.state -ne 'Stopped'){throw "Fresh service should be Stopped: $($row.serviceId)=$($row.state)"}
        if(-not [bool]$row.canStart -or [bool]$row.canStop -or [bool]$row.canRestart){throw "Fresh command state mismatch for $($row.serviceId)"}
    }

    Write-ServiceRecord -ServiceId 'local-model-api' -ProcessId 2147483000
    $stale=@(Get-MLLMWorkbenchServices -ProjectRoot $project -DataRoot $data -NetworkMode 'OFFLINE_CACHE') | Where-Object {$_.serviceId -eq 'local-model-api'} | Select-Object -First 1
    if([string]$stale.state -ne 'Stopped'){throw "Stale PID was trusted as running: $($stale.state)"}
    if([bool]$stale.canStop -or [bool]$stale.canRestart){throw 'Stale/unowned PID unexpectedly became stoppable'}
    if([string]$stale.healthSummary -notmatch 'stale|ownership|not running'){throw "Stale service summary not explicit: $($stale.healthSummary)"}

    $stdout=Join-Path $logsDir 'local-model.out.log'
    $stderr=Join-Path $logsDir 'local-model.err.log'
    1..260 | ForEach-Object { "OUT $_" } | Set-Content -LiteralPath $stdout -Encoding UTF8
    1..210 | ForEach-Object { "ERR $_" } | Set-Content -LiteralPath $stderr -Encoding UTF8
    Write-ServiceRecord -ServiceId 'local-model-api' -ProcessId $PID -Stdout $stdout -Stderr $stderr
    $running=@(Get-MLLMWorkbenchServices -ProjectRoot $project -DataRoot $data -NetworkMode 'OFFLINE_CACHE') | Where-Object {$_.serviceId -eq 'local-model-api'} | Select-Object -First 1
    if([string]$running.state -ne 'Running'){throw "Owned PID did not reconstruct Running: $($running.state)"}
    if(-not [bool]$running.canStop -or -not [bool]$running.canRestart -or [bool]$running.canStart){throw 'Owned running service command state mismatch'}
    if([int]$running.pid -ne $PID){throw 'Running service PID mismatch'}

    $tail=Get-MLLMWorkbenchServiceLogs -DataRoot $data -ServiceId 'local-model-api' -TailLines 200
    if(@($tail.stdoutLines).Count -ne 200){throw "Expected 200 stdout lines, got $(@($tail.stdoutLines).Count)"}
    if(@($tail.stderrLines).Count -ne 200){throw "Expected 200 stderr lines, got $(@($tail.stderrLines).Count)"}
    if([string]$tail.stdoutLines[0] -ne 'OUT 61' -or [string]$tail.stdoutLines[-1] -ne 'OUT 260'){throw 'Stdout tail boundaries incorrect'}
    if([string]$tail.stderrLines[0] -ne 'ERR 11' -or [string]$tail.stderrLines[-1] -ne 'ERR 210'){throw 'Stderr tail boundaries incorrect'}

    Assert-ThrowsCode -Code 'SERVICE_LOG_TAIL_INVALID' -Action { Get-MLLMWorkbenchServiceLogs -DataRoot $data -ServiceId 'local-model-api' -TailLines 0 | Out-Null }
    Assert-ThrowsCode -Code 'SERVICE_LOG_TAIL_INVALID' -Action { Get-MLLMWorkbenchServiceLogs -DataRoot $data -ServiceId 'local-model-api' -TailLines 501 | Out-Null }
    Assert-ThrowsCode -Code 'SERVICE_NOT_FOUND' -Action { Get-MLLMWorkbenchServiceLogs -DataRoot $data -ServiceId 'arbitrary-service' -TailLines 10 | Out-Null }

    $outside=Join-Path $testRoot 'outside.log'
    'SECRET' | Set-Content -LiteralPath $outside -Encoding UTF8
    Write-ServiceRecord -ServiceId 'web-workbench' -ProcessId $PID -Stdout $outside -Stderr ''
    Assert-ThrowsCode -Code 'LOG_PATH_OUTSIDE_DATA_ROOT' -Action { Get-MLLMWorkbenchServiceLogs -DataRoot $data -ServiceId 'web-workbench' -TailLines 20 | Out-Null }

    $before=(Get-ChildItem -LiteralPath $stateDir -File | Sort-Object Name | ForEach-Object { $_.Name+':'+(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash }) -join '|'
    Get-MLLMWorkbenchServices -ProjectRoot $project -DataRoot $data -NetworkMode 'OFFLINE_CACHE' | Out-Null
    $after=(Get-ChildItem -LiteralPath $stateDir -File | Sort-Object Name | ForEach-Object { $_.Name+':'+(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash }) -join '|'
    if($before -ne $after){throw 'Read-only service snapshot mutated server state'}

    Write-Host 'PHASE_B_SERVICE_ADAPTER=PASS ids=PASS stale=PASS ownership=PASS logs=PASS bounded=PASS path_guard=PASS readonly=PASS'
}finally{
    Remove-Item -LiteralPath $testRoot -Recurse -Force -ErrorAction SilentlyContinue
}
