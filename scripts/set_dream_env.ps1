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

Write-Host "DREAM_ENV_READY"
Write-Host "DREAM_HOME=$env:DREAM_HOME"

