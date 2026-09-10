[CmdletBinding()]
param(
    [ValidateRange(1, 65535)]
    [int]$Port = 8766,
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$runScript = Join-Path $PSScriptRoot 'run_dream_web.ps1'
$baseUrl = "http://127.0.0.1:$Port/"

function Test-DreamWebReady {
    try {
        $response = Invoke-WebRequest -Uri $baseUrl -UseBasicParsing -TimeoutSec 2
        return $response.StatusCode -eq 200 -and $response.Content -match '<title>Dream Windows</title>'
    } catch {
        return $false
    }
}

$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
    Select-Object -First 1
if ($listener) {
    if (-not (Test-DreamWebReady)) {
        throw "Port $Port is occupied by another application (PID $($listener.OwningProcess))."
    }

    Write-Host "DREAM_WEB_ALREADY_RUNNING PID=$($listener.OwningProcess)"
    if (-not $NoBrowser) {
        Start-Process $baseUrl
    }
    exit 0
}

$logDir = 'E:\Dream\logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$stdoutLog = Join-Path $logDir "dream-web-$Port-$stamp.out.log"
$stderrLog = Join-Path $logDir "dream-web-$Port-$stamp.err.log"
$pwshExe = (Get-Command pwsh.exe -ErrorAction Stop).Source

$launcherProcess = Start-Process -FilePath $pwshExe `
    -ArgumentList @('-NoProfile', '-File', $runScript, '-Port', [string]$Port) `
    -WorkingDirectory $repoRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput $stdoutLog `
    -RedirectStandardError $stderrLog `
    -PassThru

for ($attempt = 0; $attempt -lt 60; $attempt++) {
    Start-Sleep -Milliseconds 500
    if (Test-DreamWebReady) {
        $serverListener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
            Select-Object -First 1
        Write-Host "DREAM_WEB_READY PID=$($serverListener.OwningProcess)"
        Write-Host "URL=$baseUrl"
        Write-Host "LOG=$stdoutLog"
        if (-not $NoBrowser) {
            Start-Process $baseUrl
        }
        exit 0
    }

    if ($launcherProcess.HasExited) {
        break
    }
}

$details = @()
if (Test-Path -LiteralPath $stdoutLog) {
    $details += Get-Content -LiteralPath $stdoutLog -Tail 20
}
if (Test-Path -LiteralPath $stderrLog) {
    $details += Get-Content -LiteralPath $stderrLog -Tail 20
}
$detailText = if ($details.Count) { "`n" + ($details -join "`n") } else { '' }
throw "Dream web service did not become ready. Logs: $stdoutLog, $stderrLog$detailText"
