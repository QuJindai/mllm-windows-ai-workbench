param(
  [string]$Root = "E:\Dream"
)

$ErrorActionPreference = "Stop"
$Root = [IO.Path]::GetFullPath($Root)

if (-not $Root.StartsWith("E:\", [StringComparison]::OrdinalIgnoreCase)) {
  throw "Dream root must be on E:; received $Root"
}

$env:DREAM_HOME = $Root
$env:HF_HOME = Join-Path $Root "cache\huggingface"
$env:HUGGINGFACE_HUB_CACHE = Join-Path $Root "cache\huggingface\hub"
$env:TORCH_HOME = Join-Path $Root "cache\torch"
$env:TRANSFORMERS_CACHE = Join-Path $Root "cache\transformers"
$env:CARGO_HOME = Join-Path $Root "cache\cargo"
$env:RUSTUP_HOME = Join-Path $Root "env\rust"
$env:npm_config_cache = Join-Path $Root "cache\npm"
$env:NUGET_PACKAGES = Join-Path $Root "cache\nuget"
$env:TEMP = Join-Path $Root "temp"
$env:TMP = Join-Path $Root "temp"
$env:DREAM_MODEL_HOME = Join-Path $Root "models"
$env:DREAM_DATA_HOME = Join-Path $Root "data"
$env:DREAM_TRACE_HOME = Join-Path $Root "traces"
$env:DREAM_EXPERIMENT_HOME = Join-Path $Root "experiments"
$env:DREAM_EXPORT_HOME = Join-Path $Root "exports"
$env:DREAM_BUILD_HOME = Join-Path $Root "builds"
$env:DREAM_LOG_HOME = Join-Path $Root "logs"

$env:DREAM_CMAKE_HOME = Join-Path $Root "tools\cmake\cmake-4.4.3-windows-x86_64"
$env:DREAM_CUDA_HOME = Join-Path $Root "tools\cuda\12.9.1"
$env:CUDA_PATH = $env:DREAM_CUDA_HOME
$env:CUDA_PATH_V12_9 = $env:DREAM_CUDA_HOME
$env:CUDAToolkit_ROOT = $env:DREAM_CUDA_HOME
$env:DREAM_NINJA_HOME = Join-Path $Root "tools\ninja"
$env:DREAM_LLVM_HOME = Join-Path $Root "tools\llvm"
$env:DREAM_STABLE_DIFFUSION_CPP_ROOT = Join-Path $Root "app\stable-diffusion-cpp"
$env:DREAM_STABLE_DIFFUSION_CPP_EXE = Join-Path $env:DREAM_STABLE_DIFFUSION_CPP_ROOT "sd-cli.exe"
$nativeSelection = Join-Path $Root 'app\native-engine.json'
if (Test-Path -LiteralPath $nativeSelection) {
  $selection = Get-Content -LiteralPath $nativeSelection -Raw | ConvertFrom-Json
  $selectedEngine = [IO.Path]::GetFullPath([string]$selection.engineExe)
  if (-not $selectedEngine.StartsWith((Join-Path $Root 'app\'), [StringComparison]::OrdinalIgnoreCase) -or -not (Test-Path -LiteralPath $selectedEngine -PathType Leaf)) {
    throw "Configured native engine is invalid: $selectedEngine"
  }
  $env:DREAM_STABLE_DIFFUSION_CPP_EXE = $selectedEngine
  $env:DREAM_STABLE_DIFFUSION_CPP_ROOT = Split-Path $selectedEngine -Parent
}
$env:DREAM_SDCPP_GENERATE_WRAPPER = Join-Path $PSScriptRoot "run_stable_diffusion_wrapper.cmd"
$env:DREAM_MODEL_REGISTRY = Join-Path (Split-Path -Parent $PSScriptRoot) "config\dream\model-registry.json"

foreach ($directory in @(
  $env:HF_HOME, $env:HUGGINGFACE_HUB_CACHE, $env:TORCH_HOME,
  $env:TRANSFORMERS_CACHE, $env:CARGO_HOME, $env:RUSTUP_HOME,
  $env:npm_config_cache, $env:NUGET_PACKAGES, $env:TEMP, $env:DREAM_MODEL_HOME,
  $env:DREAM_DATA_HOME, $env:DREAM_TRACE_HOME, $env:DREAM_EXPERIMENT_HOME,
  $env:DREAM_EXPORT_HOME, $env:DREAM_BUILD_HOME, $env:DREAM_LOG_HOME
)) {
  New-Item -ItemType Directory -Force -Path $directory | Out-Null
}

$dreamBins = @(
  (Join-Path $env:DREAM_CMAKE_HOME "bin"),
  (Join-Path $env:DREAM_CUDA_HOME "bin"),
  $env:DREAM_NINJA_HOME,
  (Join-Path $env:DREAM_LLVM_HOME "bin"),
  $env:DREAM_STABLE_DIFFUSION_CPP_ROOT
)
$existingPath = @($env:Path -split ";" | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
$env:Path = (($dreamBins + $existingPath | Select-Object -Unique) -join ";")

Write-Host "DREAM_ENV_READY"
Write-Host "DREAM_HOME=$env:DREAM_HOME"
Write-Host "DREAM_STABLE_DIFFUSION_CPP_EXE=$env:DREAM_STABLE_DIFFUSION_CPP_EXE"
Write-Host "DREAM_SDCPP_GENERATE_WRAPPER=$env:DREAM_SDCPP_GENERATE_WRAPPER"
