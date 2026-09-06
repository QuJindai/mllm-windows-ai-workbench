param(
  [string]$Root = "E:\Dream"
)

$ErrorActionPreference = "Stop"
$Root = [IO.Path]::GetFullPath($Root)
$RepoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$LogRoot = Join-Path $Root "logs\w0"
New-Item -ItemType Directory -Force -Path $LogRoot | Out-Null

function Invoke-Gate {
  param(
    [string]$Name,
    [string]$ScriptPath,
    [string[]]$Arguments
  )

  $Output = @(& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $ScriptPath @Arguments 2>&1)
  $ExitCode = $LASTEXITCODE
  $LogPath = Join-Path $LogRoot ($Name + ".log")
  $Output | Out-String | Set-Content -Path $LogPath -Encoding UTF8
  [pscustomobject]@{
    name = $Name
    pass = ($ExitCode -eq 0)
    exit_code = $ExitCode
    log_path = $LogPath
    output = ($Output | ForEach-Object { [string]$_ })
  }
}

$Gates = @()
$Gates += Invoke-Gate -Name "bootstrap" -ScriptPath (Join-Path $RepoRoot "scripts\bootstrap_e_drive.ps1") -Arguments @("-Root", $Root)
$Gates += Invoke-Gate -Name "hardware" -ScriptPath (Join-Path $RepoRoot "scripts\collect_hardware.ps1") -Arguments @("-Root", $Root)
$Gates += Invoke-Gate -Name "cuda" -ScriptPath (Join-Path $RepoRoot "scripts\verify_cuda.ps1") -Arguments @()
$Gates += Invoke-Gate -Name "no-c-drive-assets" -ScriptPath (Join-Path $RepoRoot "scripts\verify_no_c_drive_assets.ps1") -Arguments @("-Root", $Root)

$Report = [ordered]@{
  timestamp = (Get-Date).ToString("o")
  dream_root = $Root
  gates = $Gates
  pass = @($Gates | Where-Object { -not $_.pass }).Count -eq 0
  hardware_json = Join-Path $Root "data\hardware.json"
}
$ReportPath = Join-Path $LogRoot "w0_acceptance.json"
$Report | ConvertTo-Json -Depth 8 | Set-Content -Path $ReportPath -Encoding UTF8

if (-not $Report.pass) {
  Write-Host "W0_ACCEPTANCE_FAIL"
  Write-Host "Wrote $ReportPath"
  exit 2
}

Write-Host "E_DRIVE_LAYOUT_PASS"
Write-Host "HARDWARE_PROBE_PASS"
Write-Host "CUDA_VISIBLE_PASS"
Write-Host "NO_C_DRIVE_DREAM_ASSET_PASS"
Write-Host "W0_ACCEPTANCE_PASS"
Write-Host "Wrote $ReportPath"
