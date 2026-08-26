[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)]
    [ValidateSet('doctor','core')]
    [string]$Scenario
)

$ErrorActionPreference='Stop'
Set-StrictMode -Version 2
$Root=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path

function Read-JsonItems([string]$Path){
    $parsed=Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
    $items=@()
    if($parsed -is [System.Array]){
        foreach($item in $parsed){$items += ,$item}
    }else{
        $items += ,$parsed
    }
    return $items
}

if($Scenario -eq 'doctor'){
    $Data=Join-Path $env:RUNNER_TEMP ('mllm-cold-doctor-'+[guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Force -Path $Data | Out-Null
    try{
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root 'Start_M_LLM_Workbench.ps1') -Doctor -DataRoot $Data -NetworkMode OFFLINE_CACHE
        $rc=$LASTEXITCODE
        if($rc -notin @(0,1)){throw "Cold checkout Doctor execution failed rc=$rc"}

        $summaryPath=Get-ChildItem -LiteralPath $Data -Recurse -Filter summary.json -File | Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if($null -eq $summaryPath){throw 'Cold checkout Doctor did not write summary.json'}
        $items=@(Read-JsonItems -Path $summaryPath.FullName)
        if($items.Count -lt 8){throw "Cold checkout Doctor returned too few checks: $($items.Count)"}

        $ids=@($items | ForEach-Object {$_.id})
        foreach($required in @('system.os','system.disk','filesystem.permissions','python.interpreter','llama.runtime','model.qwen35-4b','runtime.health','runtime.chat')){
            if($ids -notcontains $required){throw "Cold checkout Doctor missing required check: $required"}
        }

        $failedCount=@($items | Where-Object {$_.status -eq 'FAILED'}).Count
        if(($rc -eq 0) -and ($failedCount -ne 0)){throw "Doctor rc=0 but reported FAILED checks=$failedCount"}
        if(($rc -eq 1) -and ($failedCount -eq 0)){throw 'Doctor rc=1 without FAILED checks'}

        $evidence=@(Get-ChildItem -LiteralPath (Join-Path $Data 'evidence') -Filter '*.zip' -File -ErrorAction SilentlyContinue)
        if($evidence.Count -lt 1){throw 'Cold checkout Doctor did not create evidence ZIP'}
        Write-Host "COLD_CHECKOUT_DOCTOR=PASS rc=$rc count=$($items.Count) failed=$failedCount evidence=$($evidence.Count)"
    }finally{
        Remove-Item -LiteralPath $Data -Recurse -Force -ErrorAction SilentlyContinue
    }
    exit 0
}

$Data=Join-Path $env:RUNNER_TEMP ('mllm-cold-core-'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $Data | Out-Null
$ps=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$oldPath=$env:Path
$oldLocalAppData=$env:LOCALAPPDATA
$oldProgramFiles=$env:ProgramFiles
try{
    $env:Path="$env:SystemRoot\System32;$env:SystemRoot"
    $env:LOCALAPPDATA=Join-Path $Data 'fake-localappdata'
    $env:ProgramFiles=Join-Path $Data 'fake-programfiles'
    & $ps -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root 'Start_M_LLM_Workbench.ps1') -Preset Core -Cli -DataRoot $Data -NetworkMode OFFLINE_CACHE
    $rc=$LASTEXITCODE

    if($rc -ne 1){throw "Cold checkout offline Core must fail closed with rc=1, got rc=$rc"}
    $executables=@(Get-ChildItem -LiteralPath $Data -Recurse -Filter '*.exe' -File -ErrorAction SilentlyContinue)
    if($executables.Count -ne 0){throw ('Cold checkout offline Core created executable(s): '+(($executables.FullName)-join ', '))}

    $summaryPath=Get-ChildItem -LiteralPath $Data -Recurse -Filter summary.json -File | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if($null -eq $summaryPath){throw 'Cold checkout Core did not write summary.json'}
    $items=@(Read-JsonItems -Path $summaryPath.FullName)
    if(@($items | Where-Object {$_.status -eq 'BLOCKED'}).Count -lt 1){throw 'Cold checkout offline Core did not return BLOCKED'}
    if(@($items | Where-Object {$_.status -eq 'FAILED'}).Count -ne 0){throw 'Cold checkout offline Core returned FAILED instead of fail-closed BLOCKED'}
    Write-Host "COLD_CHECKOUT_CORE_FAIL_CLOSED=PASS count=$($items.Count)"
}finally{
    $env:Path=$oldPath
    $env:LOCALAPPDATA=$oldLocalAppData
    $env:ProgramFiles=$oldProgramFiles
    Remove-Item -LiteralPath $Data -Recurse -Force -ErrorAction SilentlyContinue
}
exit 0
