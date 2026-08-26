$ErrorActionPreference='Stop'
Set-StrictMode -Version 2
$Root=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$Data=Join-Path $env:TEMP ('mllm-doctor-'+[guid]::NewGuid().ToString('N'))
try{
    foreach($m in @('Core','State','Detection','Network','Download','Security','Evidence','Runtime')){
        Import-Module (Join-Path $Root "engine\$m.psm1") -Force -ErrorAction Stop
    }
    Initialize-MLLMStateStore -Root $Data | Out-Null
    Import-MLLMTasks -ProjectRoot $Root
    $results=@(Invoke-MLLMDoctor -ProjectRoot $Root -DataRoot $Data -NetworkMode 'OFFLINE_CACHE')
    if($results.Count -lt 8){throw "Doctor returned too few checks: $($results.Count)"}
    $ids=@($results | ForEach-Object {$_.id})
    foreach($required in @('system.os','system.disk','filesystem.permissions','python.interpreter','llama.runtime','model.qwen35-4b','runtime.health','runtime.chat')){
        if($ids -notcontains $required){throw "Doctor missing required check: $required"}
    }
    foreach($r in $results){
        if([string]::IsNullOrWhiteSpace([string]$r.id) -or [string]::IsNullOrWhiteSpace([string]$r.status)){throw 'Doctor returned malformed result'}
    }
    Write-Host "NORMAL_DOCTOR_OFFLINE=PASS count=$($results.Count)"
}finally{
    Remove-Item -LiteralPath $Data -Recurse -Force -ErrorAction SilentlyContinue
}
