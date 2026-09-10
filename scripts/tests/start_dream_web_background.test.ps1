[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$starter = Join-Path $repoRoot 'scripts\start_dream_web_background.ps1'
$testPort = 18766
$ownedPid = $null

function Get-PortListener {
    Get-NetTCPConnection -LocalPort $testPort -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
}

$existing = Get-PortListener
if ($existing) {
    throw "Test port $testPort is already occupied by PID $($existing.OwningProcess)."
}

try {
    & pwsh.exe -NoProfile -File $starter -Port $testPort -NoBrowser
    if ($LASTEXITCODE -ne 0) {
        throw "Background launcher exited with code $LASTEXITCODE."
    }

    $firstListener = Get-PortListener
    if (-not $firstListener) {
        throw "Launcher did not create a listener on port $testPort."
    }
    $ownedPid = $firstListener.OwningProcess

    $response = Invoke-WebRequest -Uri "http://127.0.0.1:$testPort/" -UseBasicParsing -TimeoutSec 5
    if ($response.StatusCode -ne 200 -or $response.Content -notmatch '<title>Dream Windows</title>') {
        throw 'Launcher did not serve the Dream Windows application.'
    }

    & pwsh.exe -NoProfile -File $starter -Port $testPort -NoBrowser
    if ($LASTEXITCODE -ne 0) {
        throw "Second launcher invocation exited with code $LASTEXITCODE."
    }

    $secondListener = Get-PortListener
    if (-not $secondListener -or $secondListener.OwningProcess -ne $ownedPid) {
        throw 'Repeated launch replaced or duplicated the running service.'
    }

    Write-Host 'PASS: Dream web launcher starts once and reuses the running service.'
} finally {
    if ($ownedPid) {
        $ownedProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$ownedPid" -ErrorAction SilentlyContinue
        if ($ownedProcess -and $ownedProcess.CommandLine -match 'uvicorn app:app' -and $ownedProcess.CommandLine -match "--port $testPort") {
            Stop-Process -Id $ownedPid -Force -ErrorAction SilentlyContinue
        }
    }
}
