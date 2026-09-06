param(
  [string]$Root = "E:\Dream",
  [string]$RepoRoot = "",
  [switch]$SkipGui
)

$ErrorActionPreference = "Stop"
$Root = [IO.Path]::GetFullPath($Root)
if (-not $Root.StartsWith("E:\", [StringComparison]::OrdinalIgnoreCase)) {
  throw "Dream root must be on E:; received $Root"
}
if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
  $RepoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
} else {
  $RepoRoot = [IO.Path]::GetFullPath($RepoRoot)
}

$AcceptanceRoot = Join-Path $Root "logs\acceptance"
$ReportPath = Join-Path $AcceptanceRoot "acceptance.json"
New-Item -ItemType Directory -Force -Path $AcceptanceRoot | Out-Null

function Invoke-Gate {
  param(
    [string]$Name,
    [string]$ScriptPath,
    [string[]]$Arguments
  )
  $Output = @(& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $ScriptPath @Arguments 2>&1)
  $ExitCode = $LASTEXITCODE
  $LogPath = Join-Path $AcceptanceRoot ($Name + ".log")
  $Output | Out-String | Set-Content -LiteralPath $LogPath -Encoding UTF8
  [pscustomobject]@{
    name = $Name
    pass = ($ExitCode -eq 0)
    exit_code = $ExitCode
    log_path = $LogPath
    output = @($Output | ForEach-Object { [string]$_ })
  }
}

function Invoke-NpmGate {
  param(
    [string]$Name,
    [string]$AppRoot,
    [string]$ScriptName
  )
  $PreviousLocation = Get-Location
  try {
    Set-Location -LiteralPath $AppRoot
    $Output = @(& npm.cmd run $ScriptName 2>&1)
    $ExitCode = $LASTEXITCODE
  } finally {
    Set-Location -LiteralPath $PreviousLocation
  }
  $LogPath = Join-Path $AcceptanceRoot ($Name + ".log")
  $Output | Out-String | Set-Content -LiteralPath $LogPath -Encoding UTF8
  [pscustomobject]@{
    name = $Name
    pass = ($ExitCode -eq 0)
    exit_code = $ExitCode
    log_path = $LogPath
    output = @($Output | ForEach-Object { [string]$_ })
  }
}

$W0 = Invoke-Gate "w0" (Join-Path $RepoRoot "tests\dream-windows\Invoke-DreamW0Acceptance.ps1") @("-Root", $Root)
$Registry = Invoke-Gate "model-registry" (Join-Path $RepoRoot "scripts\validate_model_registry.ps1") @(
  "-Root", $Root,
  "-RegistryPath", (Join-Path $RepoRoot "config\dream\model-registry.json")
)
$W1 = Invoke-Gate "w1-preflight" (Join-Path $RepoRoot "tests\dream-windows\Invoke-DreamW1Preflight.ps1") @(
  "-Root", $Root,
  "-RepoRoot", $RepoRoot
)

$GuiAppRoot = Join-Path $RepoRoot "apps\dream-windows"
$GuiEnabled = (-not $SkipGui) -and (Test-Path -LiteralPath (Join-Path $GuiAppRoot "package.json") -PathType Leaf)
$GuiAcceptanceDoc = Join-Path $RepoRoot "docs\dream-windows\W2_GUI_ACCEPTANCE.md"
$GuiGates = [ordered]@{
  enabled = $GuiEnabled
  app_root = $GuiAppRoot
  acceptance_doc = [ordered]@{ pass = (Test-Path -LiteralPath $GuiAcceptanceDoc -PathType Leaf); path = $GuiAcceptanceDoc }
  tests = $null
  frontend_build = $null
  dpi = $null
  e_drive = $null
  tauri_build = $null
  pass = $true
}
if ($GuiEnabled) {
  $GuiGates.tests = Invoke-NpmGate "gui-tests" $GuiAppRoot "test:run"
  $GuiGates.frontend_build = Invoke-NpmGate "gui-build" $GuiAppRoot "build"
  $GuiGates.dpi = Invoke-NpmGate "gui-dpi" $GuiAppRoot "verify:dpi"
  $GuiGates.e_drive = Invoke-NpmGate "gui-e-drive" $GuiAppRoot "verify:e-drive"
  $GuiGates.tauri_build = Invoke-NpmGate "gui-tauri-build" $GuiAppRoot "tauri:build"
  $GuiGates.pass = [bool]($GuiGates.acceptance_doc.pass -and $GuiGates.tests.pass -and $GuiGates.frontend_build.pass -and $GuiGates.dpi.pass -and $GuiGates.e_drive.pass -and $GuiGates.tauri_build.pass)
}

$HardwarePath = Join-Path $Root "data\hardware.json"
$Hardware = $null
if (Test-Path -LiteralPath $HardwarePath -PathType Leaf) {
  try { $Hardware = Get-Content -LiteralPath $HardwarePath -Raw | ConvertFrom-Json } catch { $Hardware = $null }
}
$RegistryPath = Join-Path $RepoRoot "config\dream\model-registry.json"
$RegistryData = $null
if (Test-Path -LiteralPath $RegistryPath -PathType Leaf) {
  try { $RegistryData = Get-Content -LiteralPath $RegistryPath -Raw | ConvertFrom-Json } catch { $RegistryData = $null }
}
$Model = $null
if ($null -ne $RegistryData -and $null -ne $RegistryData.models) {
  $Model = @($RegistryData.models | Where-Object { $_.model_id -eq $RegistryData.first_model_id }) | Select-Object -First 1
}

$Branch = ((& git -C $RepoRoot rev-parse --abbrev-ref HEAD 2>&1) | Out-String).Trim()
$Head = ((& git -C $RepoRoot rev-parse HEAD 2>&1) | Out-String).Trim()
$NoCDrivePass = @($W0.output | Where-Object { $_ -eq "NO_C_DRIVE_DREAM_ASSET_PASS" }).Count -gt 0
$CudaPass = @($W0.output | Where-Object { $_ -eq "CUDA_VISIBLE_PASS" }).Count -gt 0
$W0Pass = [bool]$W0.pass
$RegistryPass = [bool]$Registry.pass
$W1Pass = [bool]$W1.pass

$W1ReportPath = Join-Path $Root "logs\w1\preflight.json"
$W1Data = $null
if (Test-Path -LiteralPath $W1ReportPath -PathType Leaf) {
  try { $W1Data = Get-Content -LiteralPath $W1ReportPath -Raw | ConvertFrom-Json } catch { $W1Data = $null }
}
$BlockingCodes = @()
if ($null -ne $W1Data -and $null -ne $W1Data.checks) {
  $BlockingCodes = @($W1Data.checks | Where-Object { $_.pass -ne $true } | ForEach-Object { $_.code })
}

$Report = [ordered]@{
  schema_version = 1
  timestamp = (Get-Date).ToString("o")
  branch = $Branch
  HEAD = $Head
  dream_root = $Root
  gates = [ordered]@{
    w0 = $W0
    model_registry = $Registry
    w1_preflight = $W1
    gui_w2 = $GuiGates
    no_c_drive = [ordered]@{ pass = $NoCDrivePass; marker = "NO_C_DRIVE_DREAM_ASSET_PASS" }
  }
  hardware = [ordered]@{
    GPU = if ($null -ne $Hardware) { $Hardware.nvidia.name } else { $null }
    VRAM = if ($null -ne $Hardware) { $Hardware.nvidia.memory_total_mib } else { $null }
    CUDA = $CudaPass
    driver_version = if ($null -ne $Hardware) { $Hardware.nvidia.driver_version } else { $null }
    RAM = if ($null -ne $Hardware) { $Hardware.ram.total_bytes } else { $null }
    CPU = if ($null -ne $Hardware) { $Hardware.cpu.name } else { $null }
  }
  model_identity = [ordered]@{
    model_id = if ($null -ne $Model) { $Model.model_id } else { $null }
    display_name = if ($null -ne $Model) { $Model.display_name } else { $null }
    architecture = if ($null -ne $Model) { $Model.architecture } else { $null }
    status = if ($null -ne $Model) { $Model.status } else { $null }
    model_path = if ($null -ne $Model) { $Model.windows.path } else { $null }
  }
  generation = [ordered]@{
    windows_cuda_generation_pass = $false
    output_path = $null
    metadata_path = $null
    seed = $null
    steps = $null
    cfg = $null
    generation_time = $null
    peak_vram = $null
    peak_ram = $null
  }
  failure_codes = $BlockingCodes
  pass = ($W0Pass -and $RegistryPass -and $W1Pass -and $NoCDrivePass -and $GuiGates.pass)
}
$Report | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $ReportPath -Encoding UTF8

if (-not $Report.pass) {
  Write-Host "DREAM_ACCEPTANCE_BLOCKED"
  $BlockingCodes | ForEach-Object { Write-Host "Blocking: $_" }
  Write-Host "Wrote $ReportPath"
  exit 3
}

if ($GuiEnabled -and $GuiGates.pass) {
  Write-Host "GUI_TESTS_PASS"
  Write-Host "GUI_BUILD_PASS"
  Write-Host "GUI_DPI_PASS"
  Write-Host "GUI_E_DRIVE_PASS"
  Write-Host "GUI_TAURI_BUILD_PASS"
}

Write-Host "DREAM_ACCEPTANCE_PASS"
Write-Host "Wrote $ReportPath"
