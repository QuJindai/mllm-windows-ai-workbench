param(
  [string]$Root = "E:\Dream"
)

$ErrorActionPreference = "Stop"
$Root = [IO.Path]::GetFullPath($Root)

if (-not $Root.StartsWith("E:\", [StringComparison]::OrdinalIgnoreCase)) {
  throw "Dream root must be on E:; received $Root"
}

$EnvironmentNames = @(
  "DREAM_HOME",
  "HF_HOME",
  "HUGGINGFACE_HUB_CACHE",
  "TORCH_HOME",
  "TRANSFORMERS_CACHE",
  "CARGO_HOME",
  "RUSTUP_HOME",
  "npm_config_cache",
  "NUGET_PACKAGES",
  "TEMP",
  "TMP",
  "DREAM_MODEL_HOME",
  "DREAM_DATA_HOME",
  "DREAM_TRACE_HOME",
  "DREAM_EXPERIMENT_HOME",
  "DREAM_EXPORT_HOME",
  "DREAM_BUILD_HOME",
  "DREAM_LOG_HOME"
)

if ([string]::IsNullOrWhiteSpace($env:DREAM_HOME)) {
  . (Join-Path $PSScriptRoot "set_dream_env.ps1") -Root $Root
}

$Violations = [System.Collections.Generic.List[string]]::new()
$RootPrefix = $Root.TrimEnd("\") + "\"

foreach ($Name in $EnvironmentNames) {
  $Value = [Environment]::GetEnvironmentVariable($Name, "Process")
  if (-not [string]::IsNullOrWhiteSpace($Value)) {
    $FullValue = [IO.Path]::GetFullPath($Value)
    if (-not ($FullValue.Equals($Root, [StringComparison]::OrdinalIgnoreCase) -or $FullValue.StartsWith($RootPrefix, [StringComparison]::OrdinalIgnoreCase))) {
      $Violations.Add("$Name=$Value")
    }
  }
}

# A generic user cache is not automatically a Dream asset: this machine may
# have unrelated projects using Hugging Face or Torch. Configuration variables
# above are authoritative for Dream, while these explicitly named Dream
# directories catch legacy local installs that bypass configuration.
$Candidates = @(
  (Join-Path $env:LOCALAPPDATA "Dream"),
  (Join-Path $env:APPDATA "Dream"),
  (Join-Path $env:USERPROFILE "Dream")
)

foreach ($Path in $Candidates) {
  if (Test-Path -LiteralPath $Path) {
    $Violations.Add("C-drive Dream candidate exists: $Path")
  }
}

$ReportPath = Join-Path $Root "logs\w0\no_c_drive_assets.json"
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $ReportPath) | Out-Null
$Report = [ordered]@{
  timestamp = (Get-Date).ToString("o")
  dream_root = $Root
  pass = ($Violations.Count -eq 0)
  violations = @($Violations)
}
$Report | ConvertTo-Json -Depth 5 | Set-Content -Path $ReportPath -Encoding UTF8

if ($Violations.Count -gt 0) {
  Write-Host "NO_C_DRIVE_DREAM_ASSET_FAIL"
  $Violations | ForEach-Object { Write-Host "Violation: $_" }
  exit 2
}

Write-Host "NO_C_DRIVE_DREAM_ASSET_PASS"
Write-Host "Wrote $ReportPath"
