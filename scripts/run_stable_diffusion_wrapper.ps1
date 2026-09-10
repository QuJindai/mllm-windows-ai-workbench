param(
  [Parameter(Mandatory = $true)]
  [string]$Request
)

$ErrorActionPreference = "Stop"
$root = "E:\Dream"
Import-Module (Join-Path $PSScriptRoot "DreamEngineSupport.psm1") -Force
$engine = [Environment]::GetEnvironmentVariable('DREAM_STABLE_DIFFUSION_CPP_EXE')
if ([string]::IsNullOrWhiteSpace($engine)) { $engine = Join-Path $root "app\stable-diffusion-cpp\sd-cli.exe" }
$engine = [IO.Path]::GetFullPath($engine)
if (-not $engine.StartsWith("$root\app\", [StringComparison]::OrdinalIgnoreCase)) { throw "Native engine must be below $root\app" }
$requestPath = [IO.Path]::GetFullPath($Request)

if (-not $requestPath.StartsWith("$root\", [StringComparison]::OrdinalIgnoreCase)) {
  throw "Request must be below $root"
}
if (-not (Test-Path -LiteralPath $requestPath -PathType Leaf)) {
  throw "Request file does not exist: $requestPath"
}
if (-not (Test-Path -LiteralPath $engine -PathType Leaf)) {
  throw "stable-diffusion.cpp executable is missing: $engine"
}

$requestObject = Get-Content -LiteralPath $requestPath -Raw | ConvertFrom-Json
foreach ($field in @("model_id", "model_path", "prompt", "negative", "seed", "steps", "cfg", "width", "height", "output", "metadata")) {
  if ($null -eq $requestObject.$field -or [string]::IsNullOrWhiteSpace([string]$requestObject.$field)) {
    throw "Request field is missing: $field"
  }
}

$traceLevel = if ($null -eq $requestObject.trace_level -or [string]::IsNullOrWhiteSpace([string]$requestObject.trace_level)) { "basic" } else { [string]$requestObject.trace_level }
if (@("off", "basic", "h6", "h7") -notcontains $traceLevel) {
  throw "Unsupported trace level: $traceLevel"
}
$traceDirPath = $null
if (@("h6", "h7") -contains $traceLevel) {
  if ($null -eq $requestObject.trace_dir -or [string]::IsNullOrWhiteSpace([string]$requestObject.trace_dir)) {
    throw "Trace directory is required for microscope capture"
  }
  $traceDirPath = [IO.Path]::GetFullPath([string]$requestObject.trace_dir)
  if (-not $traceDirPath.StartsWith("$root\", [StringComparison]::OrdinalIgnoreCase)) {
    throw "Trace directory must be below $root"
  }
  New-Item -ItemType Directory -Force -Path $traceDirPath | Out-Null
}
$latentTracePath = $null
$latentTraceSupported = $false
$attentionTracePath = $null
$attentionTraceSupported = $false
if (@("h6", "h7") -contains $traceLevel) {
  $latentTracePath = Join-Path $traceDirPath "latent-metrics.jsonl"
  $nativeHelp = (& $engine --help 2>&1 | Out-String)
  $latentTraceSupported = $nativeHelp -match "--latent-trace-path"
  if (-not $latentTraceSupported) {
    Write-Host "DREAM_SDCPP_LATENT_TRACE_UNAVAILABLE native binary does not expose --latent-trace-path; using RGB projection only"
  }
  if ($traceLevel -eq "h7") {
    $attentionTracePath = $traceDirPath
    $attentionTraceSupported = $nativeHelp -match "--attention-trace-path"
    if (-not $attentionTraceSupported) {
      throw "H7 research engine does not expose --attention-trace-path: $engine"
    }
  }
}

$samplingMethod = if ($null -eq $requestObject.sampling_method -or [string]::IsNullOrWhiteSpace([string]$requestObject.sampling_method)) { "dpm++2m" } else { [string]$requestObject.sampling_method }
$scheduler = if ($null -eq $requestObject.scheduler -or [string]::IsNullOrWhiteSpace([string]$requestObject.scheduler)) { "karras" } else { [string]$requestObject.scheduler }
$validSamplingMethods = @("dpm++2m", "dpm++2m_sde", "lcm", "euler", "euler_a")
$validSchedulers = @("karras", "discrete", "exponential", "lcm")
if ($validSamplingMethods -notcontains $samplingMethod) {
  throw "Unsupported sampling method: $samplingMethod"
}
if ($validSchedulers -notcontains $scheduler) {
  throw "Unsupported scheduler: $scheduler"
}

foreach ($path in @([string]$requestObject.model_path, [string]$requestObject.output, [string]$requestObject.metadata)) {
  $fullPath = [IO.Path]::GetFullPath($path)
  if (-not $fullPath.StartsWith("$root\", [StringComparison]::OrdinalIgnoreCase)) {
    throw "Model and output paths must be below $root"
  }
}

$outputPath = [IO.Path]::GetFullPath([string]$requestObject.output)
$metadataPath = [IO.Path]::GetFullPath([string]$requestObject.metadata)
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $outputPath), (Split-Path -Parent $metadataPath), (Join-Path $root "logs\w1\samples") | Out-Null

function Get-NvidiaMemoryMiB {
  param([string]$Query)
  try {
    $value = @(nvidia-smi.exe --query-gpu=$Query --format=csv,noheader,nounits 2>$null) | Select-Object -First 1
    if ($value -match "\d+") { return [int]$Matches[0] }
  } catch {
    # Hardware sampling is diagnostic; the native command remains authoritative.
  }
  return 0
}

function Get-SafeCudaBudgetGb {
  param([int]$TotalMiB, [int]$OtherMiB)
  if ($TotalMiB -le 0) { return 4.4 }
  $availableMiB = $TotalMiB - [math]::Max(0, $OtherMiB) - 1024 - 512
  $budget = [math]::Floor(($availableMiB / 1024.0) * 10) / 10
  return [math]::Max(3.0, [math]::Round($budget, 1))
}

$totalVramMiB = Get-NvidiaMemoryMiB "memory.total"
$initialVramMiB = Get-NvidiaMemoryMiB "memory.used"
$maxVramGb = Get-SafeCudaBudgetGb $totalVramMiB $initialVramMiB
$requestedBudget = [Environment]::GetEnvironmentVariable("DREAM_CUDA_MAX_VRAM_GB")
if ($requestedBudget -match "^\d+(\.\d+)?$") {
  $maxVramGb = [math]::Max(3.0, [math]::Min($maxVramGb, [double]$requestedBudget))
}

$samplePath = Join-Path $root ("logs\w1\samples\resource-" + [guid]::NewGuid().ToString("N") + ".jsonl")
$monitor = Start-Job -ArgumentList $samplePath -ScriptBlock {
  param([string]$OutputPath)
  $peakVram = 0
  $peakDreamVram = 0
  $peakRam = 0
  while ($true) {
    try {
      $totalVramText = @(nvidia-smi.exe --query-gpu=memory.total --format=csv,noheader,nounits 2>$null) | Select-Object -First 1
      $totalVram = 0
      if ($totalVramText -match "\d+") { $totalVram = [int]$Matches[0] }
      $vramText = @(nvidia-smi.exe --query-gpu=memory.used --format=csv,noheader,nounits 2>$null) | Select-Object -First 1
      $vram = 0
      if ($vramText -match "\d+") { $vram = [int]$Matches[0] }
      $dreamVram = 0
      $dreamPids = @(Get-Process -Name "sd-cli" -ErrorAction SilentlyContinue | ForEach-Object { [int]$_.Id })
      if ($dreamPids.Count -gt 0) {
        $processRows = @(nvidia-smi.exe --query-compute-apps=pid,used_gpu_memory --format=csv,noheader,nounits 2>$null)
        foreach ($row in $processRows) {
          if ($row -match "^\s*(\d+)\s*,\s*(\d+)") {
            $sampleProcessId = [int]$Matches[1]
            if ($dreamPids -contains $sampleProcessId) { $dreamVram += [int]$Matches[2] }
          }
        }
      }
      $os = Get-CimInstance Win32_OperatingSystem
      $ram = [int64](($os.TotalVisibleMemorySize - $os.FreePhysicalMemory) * 1KB)
      if ($vram -gt $peakVram) { $peakVram = $vram }
      if ($dreamVram -gt $peakDreamVram) { $peakDreamVram = $dreamVram }
      if ($ram -gt $peakRam) { $peakRam = $ram }
      [pscustomobject]@{
        timestamp = (Get-Date).ToString("o")
        total_vram_mib = $totalVram
        vram_mib = $vram
        dream_vram_mib = $dreamVram
        ram_bytes = $ram
        peak_vram_mib = $peakVram
        peak_dream_vram_mib = $peakDreamVram
        peak_ram_bytes = $peakRam
      } | ConvertTo-Json -Compress | Add-Content -LiteralPath $OutputPath -Encoding UTF8
    } catch {
      # Resource sampling is diagnostic; it must not hide the generation result.
    }
    Start-Sleep -Milliseconds 250
  }
}

$stopwatch = [Diagnostics.Stopwatch]::StartNew()
$requestObject | Add-Member -NotePropertyName sampling_method -NotePropertyValue $samplingMethod -Force
$requestObject | Add-Member -NotePropertyName scheduler -NotePropertyValue $scheduler -Force
$disableFlashAttention = [Environment]::GetEnvironmentVariable("DREAM_DISABLE_DIFFUSION_FA") -eq "1"
$argumentPlan = New-DreamStableDiffusionArguments `
  -Request $requestObject `
  -OutputPath $outputPath `
  -MaxVramGb $maxVramGb `
  -TraceLevel $traceLevel `
  -TraceDirectory $traceDirPath `
  -LatentTraceSupported $latentTraceSupported `
  -LatentTracePath $latentTracePath `
  -AttentionTraceSupported $attentionTraceSupported `
  -AttentionTracePath $attentionTracePath `
  -DisableDiffusionFlashAttention $disableFlashAttention
$arguments = $argumentPlan.Arguments

try {
  & $engine @arguments
  $nativeExit = $LASTEXITCODE
} finally {
  $stopwatch.Stop()
  Stop-Job -Job $monitor -ErrorAction SilentlyContinue | Out-Null
  Receive-Job -Job $monitor -ErrorAction SilentlyContinue | Out-Null
  Remove-Job -Job $monitor -Force -ErrorAction SilentlyContinue
}

if ($nativeExit -ne 0) {
  throw "stable-diffusion.cpp exited with code $nativeExit"
}
if (-not (Test-Path -LiteralPath $outputPath -PathType Leaf)) {
  throw "stable-diffusion.cpp returned success without a PNG: $outputPath"
}
if ($traceLevel -eq "h7") {
  $attentionIndexPath = Join-Path $traceDirPath "attention-index.json"
  if (-not (Test-Path -LiteralPath $attentionIndexPath -PathType Leaf)) {
    throw "H7 generation returned success without attention-index.json: $attentionIndexPath"
  }
}

$postprocessStopwatch = [Diagnostics.Stopwatch]::StartNew()
$hashCachePath = Join-Path $root "cache\model-hashes.json"
$hashResult = Get-DreamCachedFileHash -Path ([string]$requestObject.model_path) -CachePath $hashCachePath
$sourceHash = $hashResult.Sha256
$samples = @(Get-Content -LiteralPath $samplePath -ErrorAction SilentlyContinue | ForEach-Object { $_ | ConvertFrom-Json })
$peakVram = if ($samples.Count -gt 0) { [int](($samples | Measure-Object -Property peak_vram_mib -Maximum).Maximum) } else { $null }
$peakDreamVram = if ($samples.Count -gt 0) { [int](($samples | Measure-Object -Property peak_dream_vram_mib -Maximum).Maximum) } else { $null }
$peakRam = if ($samples.Count -gt 0) { [int64](($samples | Measure-Object -Property peak_ram_bytes -Maximum).Maximum) } else { $null }
$metadata = [ordered]@{
  schema_version = 1
  model_id = [string]$requestObject.model_id
  model_path = [string]$requestObject.model_path
  model_sha256 = $sourceHash
  architecture = "SDXL"
  dmd2 = [ordered]@{ enabled = $false; reason = "No dedicated DMD2 distillation artifact is asserted by the Windows runtime; standard SDXL sampling profile is used" }
  prompt = [string]$requestObject.prompt
  negative_prompt = [string]$requestObject.negative
  seed = [int]$requestObject.seed
  steps = [int]$requestObject.steps
  cfg = [double]$requestObject.cfg
  width = [int]$requestObject.width
  height = [int]$requestObject.height
  sampling_method = $samplingMethod
  scheduler = $scheduler
  backend = "cuda"
  total_vram_mib = $totalVramMiB
  initial_vram_mib = $initialVramMiB
  cuda_budget_gb = $maxVramGb
  peak_vram_mib = $peakVram
  peak_dream_vram_mib = $peakDreamVram
  peak_ram_bytes = $peakRam
  generation_time_ms = $stopwatch.ElapsedMilliseconds
  engine_wall_time_ms = $stopwatch.ElapsedMilliseconds
  postprocess_time_ms = $postprocessStopwatch.ElapsedMilliseconds
  flash_attention = [bool]$argumentPlan.FlashAttention
  model_hash_cache_hit = [bool]$hashResult.CacheHit
  output = $outputPath
  generated_at = (Get-Date).ToString("o")
}
$metadata | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $metadataPath -Encoding UTF8
Write-Host "DREAM_SDCPP_GENERATION_PASS"
Write-Host "output=$outputPath"
Write-Host "metadata=$metadataPath"
$traceFrames = @()
if ($null -ne $traceDirPath -and (Test-Path -LiteralPath $traceDirPath -PathType Container)) {
  $traceFrames = @(Get-ChildItem -LiteralPath $traceDirPath -Filter "latent-step-*.png" -File | Sort-Object Name | ForEach-Object { $_.Name })
}
[ordered]@{
  trace_level = $traceLevel
  trace_dir = $traceDirPath
  latent_trace_path = if ($latentTraceSupported) { $latentTracePath } else { $null }
  latent_trace_supported = $latentTraceSupported
  latent_preview_frames = $traceFrames
} | ConvertTo-Json -Compress | Write-Host
