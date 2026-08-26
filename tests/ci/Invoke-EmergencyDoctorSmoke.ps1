$ErrorActionPreference='Stop'
$Root=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$Data=Join-Path $env:TEMP ('mllm-emergency-'+[guid]::NewGuid().ToString('N'))
try{
    . (Join-Path $Root 'engine\EmergencyDoctor.ps1')
    if(Get-Module | Where-Object {$_.Name -eq 'Core'}){throw 'Core module was already imported before emergency test'}
    $r=Invoke-MLLMEmergencyDoctor -ProjectRoot $Root -DataRoot $Data -Cause 'ci-smoke'
    if(-not $r){throw 'Emergency Doctor returned null'}
    if(-not(Test-Path -LiteralPath $r.json)){throw 'Emergency Doctor JSON evidence missing'}
    if(-not(Test-Path -LiteralPath $r.text)){throw 'Emergency Doctor text evidence missing'}
    if(Get-Module | Where-Object {$_.Name -eq 'Core'}){throw 'Emergency Doctor imported Core unexpectedly'}
    Write-Host 'EMERGENCY_DOCTOR_SMOKE=PASS'
}finally{Remove-Item -LiteralPath $Data -Recurse -Force -ErrorAction SilentlyContinue}
