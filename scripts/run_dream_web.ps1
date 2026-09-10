[CmdletBinding()]
param(
    [switch]$Build,
    [switch]$OpenBrowser,
    [int]$Port = 8866,
    [string]$EngineExe = ''
)

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$dreamRoot = "E:\Dream"
. (Join-Path $PSScriptRoot 'set_dream_env.ps1') -Root $dreamRoot
$frontendDist = Join-Path $dreamRoot "builds\dream-windows\frontend"

$occupied = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($occupied -and $Port -eq 8765) {
    Write-Warning "Port 8765 is already occupied; using localhost port 8866 instead."
    $Port = 8866
}

$env:DREAM_HOME = $dreamRoot
$env:DREAM_REPO_ROOT = $repoRoot
$env:DREAM_MODEL_REGISTRY = Join-Path $repoRoot "config\dream\model-registry.json"
$env:DREAM_CORE_EXE = Join-Path $dreamRoot "app\current\dream-core.exe"
if (-not [string]::IsNullOrWhiteSpace($EngineExe)) {
    $env:DREAM_STABLE_DIFFUSION_CPP_EXE = [IO.Path]::GetFullPath($EngineExe)
    $env:DREAM_STABLE_DIFFUSION_CPP_ROOT = Split-Path $env:DREAM_STABLE_DIFFUSION_CPP_EXE -Parent
}
$env:DREAM_SDCPP_GENERATE_WRAPPER = Join-Path $repoRoot "scripts\run_stable_diffusion_wrapper.cmd"
$env:DREAM_FRONTEND_DIST = $frontendDist
$env:DREAM_WEB_HOST = "127.0.0.1"
$env:DREAM_WEB_PORT = [string]$Port

if ($Build -or -not (Test-Path (Join-Path $frontendDist "index.html"))) {
    Push-Location (Join-Path $repoRoot "apps\dream-windows")
    try {
        npm.cmd run build
        if ($LASTEXITCODE -ne 0) { throw "Dream frontend build failed with exit code $LASTEXITCODE" }
    } finally {
        Pop-Location
    }
}

if ($OpenBrowser) {
    Start-Process "http://127.0.0.1:$Port"
}

Push-Location (Join-Path $repoRoot "apps\dream-windows\server")
try {
    python -m uvicorn app:app --host $env:DREAM_WEB_HOST --port ([int]$env:DREAM_WEB_PORT)
} finally {
    Pop-Location
}
