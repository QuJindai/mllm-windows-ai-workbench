param(
  [string]$Root = "E:\Dream"
)

$ErrorActionPreference = "Stop"
$Root = [IO.Path]::GetFullPath($Root)

if (-not $Root.StartsWith("E:\", [StringComparison]::OrdinalIgnoreCase)) {
  throw "Dream root must be on E:; received $Root"
}

. (Join-Path $PSScriptRoot "set_dream_env.ps1") -Root $Root

$OutputPath = Join-Path $Root "data\hardware.json"
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $OutputPath) | Out-Null

$Cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
$Os = Get-CimInstance Win32_OperatingSystem
$Cs = Get-CimInstance Win32_ComputerSystem
$EDisk = Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='E:'"

if (-not $EDisk) {
  throw "E_DRIVE_LAYOUT_FAIL: E: is not available"
}

try {
  $NvidiaRaw = @(nvidia-smi --query-gpu=name,memory.total,memory.free,driver_version,power.limit --format=csv,noheader,nounits 2>$null)
  if ($LASTEXITCODE -ne 0 -or $NvidiaRaw.Count -eq 0 -or [string]::IsNullOrWhiteSpace([string]$NvidiaRaw[0])) {
    throw "nvidia-smi returned no GPU data"
  }

  $Parts = ([string]$NvidiaRaw[0]) -split ","
  if ($Parts.Count -lt 5) {
    throw "Unexpected nvidia-smi output: $($NvidiaRaw[0])"
  }

  $memoryTotal = [int]$Parts[1].Trim()
  $memoryFree = [int]$Parts[2].Trim()
  $powerLimit = $null
  $powerText = $Parts[4].Trim()
  $powerValue = 0.0
  if ([double]::TryParse($powerText, [Globalization.NumberStyles]::Float, [Globalization.CultureInfo]::InvariantCulture, [ref]$powerValue)) {
    $powerLimit = $powerValue
  }

  $Nvidia = [ordered]@{
    name = $Parts[0].Trim()
    memory_total_mib = $memoryTotal
    memory_free_mib = $memoryFree
    driver_version = $Parts[3].Trim()
    power_limit_w = $powerLimit
  }
}
catch {
  Write-Host "CUDA_VISIBLE_FAIL"
  throw "CUDA_VISIBLE_FAIL: $($_.Exception.Message)"
}

$MemoryModules = @(Get-CimInstance Win32_PhysicalMemory | ForEach-Object {
  [ordered]@{
    locator = $_.DeviceLocator
    manufacturer = $_.Manufacturer
    part_number = ([string]$_.PartNumber).Trim()
    capacity_bytes = [int64]$_.Capacity
    rated_speed = [int]$_.Speed
    configured_clock_speed_mhz = [int]$_.ConfiguredClockSpeed
    configured_voltage_mv = [int]$_.ConfiguredVoltage
    smbios_memory_type = [int]$_.SMBIOSMemoryType
  }
})

$Result = [ordered]@{
  timestamp = (Get-Date).ToString("o")
  computer = [ordered]@{
    name = $env:COMPUTERNAME
    manufacturer = $Cs.Manufacturer
    model = $Cs.Model
    system_type = $Cs.SystemType
  }
  os = [ordered]@{
    caption = $Os.Caption
    version = $Os.Version
    build = $Os.BuildNumber
  }
  cpu = [ordered]@{
    name = $Cpu.Name
    cores = [int]$Cpu.NumberOfCores
    logical_processors = [int]$Cpu.NumberOfLogicalProcessors
  }
  ram = [ordered]@{
    total_bytes = [int64]$Cs.TotalPhysicalMemory
    free_bytes = [int64]$Os.FreePhysicalMemory * 1KB
    module_count = $MemoryModules.Count
    modules = $MemoryModules
  }
  nvidia = $Nvidia
  e_drive = [ordered]@{
    root = $Root
    total_bytes = [int64]$EDisk.Size
    free_bytes = [int64]$EDisk.FreeSpace
    used_bytes = [int64]($EDisk.Size - $EDisk.FreeSpace)
  }
}

$Result | ConvertTo-Json -Depth 8 | Set-Content -Path $OutputPath -Encoding UTF8

if ($Nvidia.memory_total_mib -lt 5500) {
  Write-Warning "VRAM lower than expected 6 GB profile: $($Nvidia.memory_total_mib) MiB"
}

Write-Host "HARDWARE_PROBE_PASS"
Write-Host "CUDA_VISIBLE_PASS"
Write-Host "Wrote $OutputPath"

