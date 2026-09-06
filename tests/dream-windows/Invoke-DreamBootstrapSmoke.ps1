$ErrorActionPreference = "Stop"

$Root = Join-Path "E:\Dream\test-runs" ("w0-" + [guid]::NewGuid().ToString("N"))
$Bootstrap = Join-Path $PSScriptRoot "..\..\scripts\bootstrap_e_drive.ps1"
$EnvironmentScript = Join-Path $PSScriptRoot "..\..\scripts\set_dream_env.ps1"

try {
  if (-not (Test-Path -LiteralPath $Bootstrap)) { throw "Missing bootstrap script: $Bootstrap" }
  if (-not (Test-Path -LiteralPath $EnvironmentScript)) { throw "Missing environment script: $EnvironmentScript" }

  & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Bootstrap -Root $Root
  if ($LASTEXITCODE -ne 0) { throw "Bootstrap failed with exit code $LASTEXITCODE" }

  . $EnvironmentScript -Root $Root
  if ($env:DREAM_HOME -ne [IO.Path]::GetFullPath($Root)) { throw "DREAM_HOME was not redirected to the test root" }

  $required = @(
    "app\current",
    "src",
    "models\windows\gguf",
    "models\windows\manifests",
    "cache\huggingface\hub",
    "cache\torch",
    "cache\cargo",
    "cache\npm",
    "env\venv",
    "data\history",
    "data\metadata",
    "experiments\fusion",
    "traces\runtime",
    "exports",
    "logs",
    "temp",
    "builds\release",
    "ci\cache"
  )

  foreach ($relative in $required) {
    $path = Join-Path $Root $relative
    if (-not (Test-Path -LiteralPath $path -PathType Container)) { throw "Missing generated directory: $path" }
    if (-not ([IO.Path]::GetFullPath($path)).StartsWith(([IO.Path]::GetFullPath($Root) + "\"), [StringComparison]::OrdinalIgnoreCase)) {
      throw "Generated path escaped root: $path"
    }
  }

  Write-Host "E_DRIVE_LAYOUT_PASS"
  Write-Host "DREAM_ENV_READY"
  Write-Host "DREAM_BOOTSTRAP_SMOKE_PASS"
}
finally {
  if (Test-Path -LiteralPath $Root) {
    Remove-Item -LiteralPath $Root -Recurse -Force -ErrorAction SilentlyContinue
  }
}

