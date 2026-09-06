param(
  [string]$Root = "E:\Dream",
  [string]$RepoRoot = ""
)

$ErrorActionPreference = "Stop"
$Root = [IO.Path]::GetFullPath($Root)
if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
  $RepoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
}
$RepoRoot = [IO.Path]::GetFullPath($RepoRoot)
$LogRoot = Join-Path $Root "logs\w1"
New-Item -ItemType Directory -Force -Path $LogRoot | Out-Null
$Prepare = Join-Path $RepoRoot "scripts\prepare_dream_core.ps1"
$Output = @(& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Prepare -Root $Root -RepoRoot $RepoRoot 2>&1)
$ExitCode = $LASTEXITCODE
$Output | Out-String | Set-Content -LiteralPath (Join-Path $LogRoot "preflight-wrapper.log") -Encoding UTF8
$Output | ForEach-Object { Write-Host $_ }
if ($ExitCode -ne 0) {
  Write-Host "W1_PREFLIGHT_BLOCKED"
  exit $ExitCode
}
Write-Host "W1_PREFLIGHT_PASS"
