$ErrorActionPreference='Stop'
Set-StrictMode -Version 2
$Root=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$Preflight=Join-Path $Root 'M_LLM_PHYSICAL_PREFLIGHT.ps1'
if(-not(Test-Path -LiteralPath $Preflight -PathType Leaf)){throw 'PHYSICAL_PREFLIGHT_SCRIPT_MISSING'}

$text=Get-Content -LiteralPath $Preflight -Raw -Encoding UTF8
$forbidden=@(
    '(?i)winget\s+install',
    '(?i)msiexec(?:\.exe)?',
    '(?i)pnputil(?:\.exe)?',
    '(?i)dism(?:\.exe)?',
    '(?i)schtasks(?:\.exe)?',
    '(?i)reg(?:\.exe)?\s+(add|delete)',
    '(?i)Set-ItemProperty',
    '(?i)New-ItemProperty',
    '(?i)Invoke-WebRequest',
    '(?i)Start-BitsTransfer'
)
foreach($pattern in $forbidden){
    if($text -match $pattern){throw "PHYSICAL_PREFLIGHT_FORBIDDEN_ACTION pattern=$pattern"}
}

$Data=Join-Path $env:RUNNER_TEMP ('mllm-physical-preflight-'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $Data | Out-Null
try{
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Preflight -DataRoot $Data -SkipEventLog -SkipDriverInventory
    if($LASTEXITCODE -ne 0){throw "Physical preflight smoke failed rc=$LASTEXITCODE"}

    $reportFile=Get-ChildItem -LiteralPath $Data -Recurse -Filter 'physical_preflight.json' -File | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if($null -eq $reportFile){throw 'Physical preflight did not create physical_preflight.json'}
    $report=Get-Content -LiteralPath $reportFile.FullName -Raw -Encoding UTF8 | ConvertFrom-Json

    if([bool]$report.core_install_authorized){throw 'Physical preflight must never authorize Core installation'}
    if([string]$report.bootstrap.status -ne 'PASS'){throw "Physical preflight bootstrap status=$($report.bootstrap.status)"}
    if([int]$report.cli.exit_code -ne 0){throw "Physical preflight CLI rc=$($report.cli.exit_code)"}
    if([int]$report.doctor.exit_code -notin @(0,1)){throw "Physical preflight Doctor rc=$($report.doctor.exit_code)"}

    $executables=@(Get-ChildItem -LiteralPath $Data -Recurse -Filter '*.exe' -File -ErrorAction SilentlyContinue)
    if($executables.Count -ne 0){throw ('Physical preflight created executable payload(s): '+(($executables.FullName)-join ', '))}

    Write-Host "PHYSICAL_PREFLIGHT_SMOKE=PASS report=$($reportFile.FullName) doctor_rc=$($report.doctor.exit_code)"
}finally{
    Remove-Item -LiteralPath $Data -Recurse -Force -ErrorAction SilentlyContinue
}
