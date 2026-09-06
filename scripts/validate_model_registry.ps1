param(
  [string]$Root = "E:\Dream",
  [string]$RegistryPath = ""
)

$ErrorActionPreference = "Stop"
$Root = [IO.Path]::GetFullPath($Root)
if (-not $Root.StartsWith("E:\", [StringComparison]::OrdinalIgnoreCase)) {
  throw "Dream root must be on E:; received $Root"
}

if ([string]::IsNullOrWhiteSpace($RegistryPath)) {
  $RegistryPath = Join-Path $PSScriptRoot "..\config\dream\model-registry.json"
}
$RegistryPath = [IO.Path]::GetFullPath($RegistryPath)
$ReportPath = Join-Path $Root "data\metadata\model-registry-validation.json"
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $ReportPath) | Out-Null

$Errors = [System.Collections.Generic.List[string]]::new()
$Warnings = [System.Collections.Generic.List[string]]::new()
$RootPrefix = $Root.TrimEnd("\") + "\"

function Add-Error([string]$Message) {
  $script:Errors.Add($Message)
}

function Test-UnderRoot([string]$Value, [string]$Field) {
  if ([string]::IsNullOrWhiteSpace($Value)) {
    Add-Error "$Field is empty"
    return $false
  }
  if ($Value -match "(?i)unet\.bin") {
    Add-Error "$Field must not reference unet.bin"
    return $false
  }
  try {
    $Full = [IO.Path]::GetFullPath($Value)
  } catch {
    Add-Error "$Field is not a valid path: $Value"
    return $false
  }
  if (-not ($Full.Equals($Root, [StringComparison]::OrdinalIgnoreCase) -or $Full.StartsWith($RootPrefix, [StringComparison]::OrdinalIgnoreCase))) {
    Add-Error "$Field is outside Dream root: $Value"
    return $false
  }
  return $true
}

function Test-Sha256($Value, [string]$Field, [bool]$AllowNull) {
  if ($null -eq $Value) {
    if (-not $AllowNull) { Add-Error "$Field is required" }
    return
  }
  if (-not ($Value -is [string]) -or $Value -notmatch "(?i)^[0-9a-f]{64}$") {
    Add-Error "$Field must be a 64-character SHA-256 hex string or null"
  }
}

$Registry = $null
try {
  if (-not (Test-Path -LiteralPath $RegistryPath -PathType Leaf)) {
    Add-Error "Registry file not found: $RegistryPath"
  } else {
    $Registry = Get-Content -LiteralPath $RegistryPath -Raw | ConvertFrom-Json
  }
} catch {
  Add-Error "Registry JSON could not be parsed: $($_.Exception.Message)"
}

if ($null -ne $Registry) {
  if ($Registry.schema_version -ne 1) { Add-Error "schema_version must be 1" }
  if ($Registry.dream_root -ne $Root) { Add-Error "dream_root must equal $Root" }
  if ($null -eq $Registry.models -or @($Registry.models).Count -eq 0) {
    Add-Error "models must contain at least one entry"
  } else {
    $ModelIds = @($Registry.models | ForEach-Object { $_.model_id })
    if ([string]::IsNullOrWhiteSpace($Registry.first_model_id) -or $ModelIds -notcontains $Registry.first_model_id) {
      Add-Error "first_model_id must identify an entry in models"
    }

    foreach ($Model in @($Registry.models)) {
      $Prefix = "model[$($Model.model_id)]"
      foreach ($Field in @("model_id", "display_name", "architecture", "status")) {
        if ([string]::IsNullOrWhiteSpace([string]$Model.$Field)) { Add-Error "$Prefix.$Field is required" }
      }
      if ($Model.status -notin @("uninstalled", "installed")) { Add-Error "$Prefix.status is invalid" }
      if ($null -eq $Model.dmd2 -or $Model.dmd2.enabled -ne $true) { Add-Error "$Prefix.dmd2.enabled must be true for the first model" }
      if ($null -eq $Model.source) { Add-Error "$Prefix.source is required" } else {
        Test-UnderRoot ([string]$Model.source.path) "$Prefix.source.path" | Out-Null
        Test-Sha256 $Model.source.sha256 "$Prefix.source.sha256" ($Model.status -eq "uninstalled")
      }
      if ($null -eq $Model.windows) {
        Add-Error "$Prefix.windows is required"
      } else {
        if ($Model.windows.format -ne "gguf") { Add-Error "$Prefix.windows.format must be gguf" }
        Test-UnderRoot ([string]$Model.windows.path) "$Prefix.windows.path" | Out-Null
        if ([string]$Model.windows.path -notmatch "(?i)\.gguf$") { Add-Error "$Prefix.windows.path must end in .gguf" }
        Test-Sha256 $Model.windows.sha256 "$Prefix.windows.sha256" ($Model.status -eq "uninstalled")
        if ($Model.status -eq "installed" -and -not (Test-Path -LiteralPath $Model.windows.path -PathType Leaf)) {
          Add-Error "$Prefix.windows.path is marked installed but does not exist"
        }
        if ($Model.status -eq "uninstalled") { $Warnings.Add("$Prefix is explicitly uninstalled; W1 generation must remain blocked") }
      }
      if ($null -eq $Model.android_reference) {
        Add-Error "$Prefix.android_reference is required"
      } else {
        if ([string]::IsNullOrWhiteSpace([string]$Model.android_reference.branch)) { Add-Error "$Prefix.android_reference.branch is required" }
        if ([string]$Model.android_reference.commit -notmatch "^[0-9a-f]{40}$") { Add-Error "$Prefix.android_reference.commit must be a 40-character commit" }
        if ($Model.android_reference.artifact_policy -ne "reference-only") { Add-Error "$Prefix.android_reference.artifact_policy must be reference-only" }
      }
    }
  }
}

$Report = [ordered]@{
  timestamp = (Get-Date).ToString("o")
  registry_path = $RegistryPath
  dream_root = $Root
  pass = ($Errors.Count -eq 0)
  errors = @($Errors)
  warnings = @($Warnings)
}
$Report | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $ReportPath -Encoding UTF8

if ($Errors.Count -gt 0) {
  Write-Host "MODEL_REGISTRY_FAIL"
  $Errors | ForEach-Object { Write-Host "Error: $_" }
  Write-Host "Wrote $ReportPath"
  exit 2
}

Write-Host "MODEL_REGISTRY_PASS"
$Warnings | ForEach-Object { Write-Host "Warning: $_" }
Write-Host "Wrote $ReportPath"
