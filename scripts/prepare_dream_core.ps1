param(
  [string]$Root = "E:\Dream",
  [string]$RepoRoot = "",
  [switch]$Build
)

$ErrorActionPreference = "Stop"
$Root = [IO.Path]::GetFullPath($Root)
if (-not $Root.StartsWith("E:\", [StringComparison]::OrdinalIgnoreCase)) {
  throw "Dream root must be on E:; received $Root"
}
if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
  $RepoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
} else {
  $RepoRoot = [IO.Path]::GetFullPath($RepoRoot)
}

$LogRoot = Join-Path $Root "logs\w1"
$AppRoot = Join-Path $Root "app\current"
$BuildRoot = Join-Path $Root "builds\dream-core"
$RegistryPath = Join-Path $RepoRoot "config\dream\model-registry.json"
$ReportPath = Join-Path $LogRoot "preflight.json"
New-Item -ItemType Directory -Force -Path $LogRoot, $AppRoot, $BuildRoot | Out-Null

$Checks = [System.Collections.Generic.List[object]]::new()
function Add-Check([string]$Name, [bool]$Pass, [string]$Code, [string]$Detail, [string]$Path = "") {
  $script:Checks.Add([pscustomobject]@{
    name = $Name
    pass = $Pass
    code = $Code
    detail = $Detail
    path = $Path
  })
}

$CMake = Get-Command cmake.exe -ErrorAction SilentlyContinue
if ($null -eq $CMake) {
  Add-Check "cmake" $false "CMAKE_MISSING" "cmake.exe is not available on PATH"
} else {
  Add-Check "cmake" $true "CMAKE_AVAILABLE" $CMake.Source $CMake.Source
}

$Nvcc = Get-Command nvcc.exe -ErrorAction SilentlyContinue
if ($null -eq $Nvcc) {
  Add-Check "cuda-toolkit" $false "CUDA_TOOLKIT_MISSING" "nvcc.exe is not available; the NVIDIA driver is checked separately by nvidia-smi"
} else {
  Add-Check "cuda-toolkit" $true "CUDA_TOOLKIT_AVAILABLE" $Nvcc.Source $Nvcc.Source
}

$Smi = Get-Command nvidia-smi.exe -ErrorAction SilentlyContinue
if ($null -eq $Smi) {
  Add-Check "cuda-driver" $false "CUDA_DRIVER_MISSING" "nvidia-smi.exe is not available"
} else {
  $SmiOutput = @(& $Smi.Source --query-gpu=name,memory.total,driver_version --format=csv,noheader,nounits 2>&1)
  if ($LASTEXITCODE -eq 0 -and $SmiOutput.Count -gt 0) {
    Add-Check "cuda-driver" $true "CUDA_VISIBLE_PASS" (($SmiOutput -join " ").Trim()) $Smi.Source
  } else {
    Add-Check "cuda-driver" $false "CUDA_VISIBLE_FAIL" (($SmiOutput -join " ").Trim()) $Smi.Source
  }
}

$EngineRoot = $env:DREAM_STABLE_DIFFUSION_CPP_ROOT
if ([string]::IsNullOrWhiteSpace($EngineRoot)) { $EngineRoot = Join-Path $Root "src\stable-diffusion.cpp" }
$EngineExe = $env:DREAM_STABLE_DIFFUSION_CPP_EXE
if ([string]::IsNullOrWhiteSpace($EngineExe)) { $EngineExe = Join-Path $EngineRoot "build\bin\sd-cli.exe" }
if (-not (Test-Path -LiteralPath $EngineRoot -PathType Container) -or -not (Test-Path -LiteralPath $EngineExe -PathType Leaf)) {
  Add-Check "stable-diffusion.cpp" $false "STABLE_DIFFUSION_CPP_MISSING" "A configured stable-diffusion.cpp root and CUDA executable are required" $EngineRoot
} else {
  Add-Check "stable-diffusion.cpp" $true "STABLE_DIFFUSION_CPP_AVAILABLE" $EngineExe $EngineExe
}

if (-not (Test-Path -LiteralPath $RegistryPath -PathType Leaf)) {
  Add-Check "model-registry" $false "MODEL_REGISTRY_MISSING" "Registry file is missing" $RegistryPath
  $Registry = $null
} else {
  $Registry = Get-Content -LiteralPath $RegistryPath -Raw | ConvertFrom-Json
  $Validator = Join-Path $RepoRoot "scripts\validate_model_registry.ps1"
  $ValidationOutput = @(& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Validator -Root $Root -RegistryPath $RegistryPath 2>&1)
  $ValidationExit = $LASTEXITCODE
  Add-Check "model-registry" ($ValidationExit -eq 0) ($(if ($ValidationExit -eq 0) { "MODEL_REGISTRY_PASS" } else { "MODEL_REGISTRY_FAIL" })) (($ValidationOutput -join " ").Trim()) $RegistryPath
}

$Model = $null
if ($null -ne $Registry -and $null -ne $Registry.models) {
  $Model = @($Registry.models | Where-Object { $_.model_id -eq $Registry.first_model_id }) | Select-Object -First 1
}
if ($null -eq $Model) {
  Add-Check "cyberrealistic-v10-dmd2" $false "CYBERREALISTIC_MODEL_MISSING" "The first registered model entry is missing"
} elseif ($Model.status -ne "installed" -or -not (Test-Path -LiteralPath ([string]$Model.windows.path) -PathType Leaf)) {
  Add-Check "cyberrealistic-v10-dmd2" $false "CYBERREALISTIC_MODEL_MISSING" "The first model is not installed as a verified Windows GGUF" ([string]$Model.windows.path)
} else {
  Add-Check "cyberrealistic-v10-dmd2" $true "CYBERREALISTIC_MODEL_AVAILABLE" "Installed GGUF present" ([string]$Model.windows.path)
}

$Wrapper = $env:DREAM_SDCPP_GENERATE_WRAPPER
if ([string]::IsNullOrWhiteSpace($Wrapper) -or -not (Test-Path -LiteralPath $Wrapper -PathType Leaf)) {
  Add-Check "native-wrapper" $false "NATIVE_BACKEND_WRAPPER_MISSING" "A verified stable-diffusion.cpp invocation wrapper is not configured"
} else {
  Add-Check "native-wrapper" $true "NATIVE_BACKEND_WRAPPER_AVAILABLE" $Wrapper $Wrapper
}

$Pass = @($Checks | Where-Object { -not $_.pass }).Count -eq 0
$Report = [ordered]@{
  timestamp = (Get-Date).ToString("o")
  dream_root = $Root
  repo_root = $RepoRoot
  pass = $Pass
  checks = @($Checks)
  build_requested = [bool]$Build
  build_output = $AppRoot
}
$Report | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $ReportPath -Encoding UTF8

if (-not $Pass) {
  Write-Host "W1_PREFLIGHT_BLOCKED"
  $Checks | Where-Object { -not $_.pass } | ForEach-Object { Write-Host "$($_.code): $($_.detail)" }
  Write-Host "Wrote $ReportPath"
  exit 3
}

if ($Build) {
  & $CMake.Source -S (Join-Path $RepoRoot "dream\core") -B $BuildRoot -DCMAKE_RUNTIME_OUTPUT_DIRECTORY=$AppRoot
  if ($LASTEXITCODE -ne 0) { throw "CMake configure failed" }
  & $CMake.Source --build $BuildRoot --config Release
  if ($LASTEXITCODE -ne 0) { throw "CMake build failed" }
}

Write-Host "W1_PREFLIGHT_PASS"
Write-Host "Wrote $ReportPath"
