Set-StrictMode -Version Latest

function Get-DreamCachedFileHash {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory = $true)]
    [string]$Path,

    [Parameter(Mandatory = $true)]
    [string]$CachePath
  )

  $item = Get-Item -LiteralPath $Path -ErrorAction Stop
  if ($item.PSIsContainer) {
    throw "Hash source must be a file: $Path"
  }

  $resolvedPath = $item.FullName
  $resolvedCachePath = [IO.Path]::GetFullPath($CachePath)
  $length = [int64]$item.Length
  $lastWriteTimeUtcTicks = [int64]$item.LastWriteTimeUtc.Ticks
  $entries = @()

  if (Test-Path -LiteralPath $resolvedCachePath -PathType Leaf) {
    try {
      $cache = Get-Content -LiteralPath $resolvedCachePath -Raw -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop
      if ($null -ne $cache.entries) {
        $entries = @($cache.entries)
      }
    } catch {
      $entries = @()
    }
  }

  $cached = $entries | Where-Object {
    [string]::Equals([string]$_.path, $resolvedPath, [StringComparison]::OrdinalIgnoreCase) -and
    [int64]$_.length -eq $length -and
    [int64]$_.last_write_time_utc_ticks -eq $lastWriteTimeUtcTicks -and
    [string]$_.sha256 -match '^[0-9A-Fa-f]{64}$'
  } | Select-Object -First 1

  if ($null -ne $cached) {
    return [pscustomobject]@{
      Path = $resolvedPath
      Sha256 = ([string]$cached.sha256).ToUpperInvariant()
      CacheHit = $true
    }
  }

  $hashAlgorithm = [Security.Cryptography.SHA256]::Create()
  $hashStream = [IO.File]::OpenRead($resolvedPath)
  try {
    $sha256 = (($hashAlgorithm.ComputeHash($hashStream) | ForEach-Object { $_.ToString("x2") }) -join "").ToUpperInvariant()
  } finally {
    $hashStream.Dispose()
    $hashAlgorithm.Dispose()
  }
  $updatedEntries = @($entries | Where-Object {
    -not [string]::Equals([string]$_.path, $resolvedPath, [StringComparison]::OrdinalIgnoreCase)
  })
  $updatedEntries += [pscustomobject]@{
    path = $resolvedPath
    length = $length
    last_write_time_utc_ticks = $lastWriteTimeUtcTicks
    sha256 = $sha256
  }

  $cacheDirectory = Split-Path -Parent $resolvedCachePath
  if ([string]::IsNullOrWhiteSpace($cacheDirectory)) {
    $cacheDirectory = (Get-Location).Path
  }
  New-Item -ItemType Directory -Force -Path $cacheDirectory | Out-Null
  $temporaryPath = Join-Path $cacheDirectory ((Split-Path -Leaf $resolvedCachePath) + "." + [guid]::NewGuid().ToString("N") + ".tmp")
  try {
    [ordered]@{
      schema_version = 1
      entries = $updatedEntries
    } | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $temporaryPath -Encoding UTF8
    Move-Item -LiteralPath $temporaryPath -Destination $resolvedCachePath -Force
  } finally {
    if (Test-Path -LiteralPath $temporaryPath) {
      Remove-Item -LiteralPath $temporaryPath -Force -ErrorAction SilentlyContinue
    }
  }

  return [pscustomobject]@{
    Path = $resolvedPath
    Sha256 = $sha256
    CacheHit = $false
  }
}

function New-DreamStableDiffusionArguments {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory = $true)]
    [psobject]$Request,

    [Parameter(Mandatory = $true)]
    [string]$OutputPath,

    [Parameter(Mandatory = $true)]
    [double]$MaxVramGb,

    [ValidateSet("off", "basic", "h6", "h7")]
    [string]$TraceLevel = "basic",

    [string]$TraceDirectory,

    [bool]$LatentTraceSupported = $false,

    [string]$LatentTracePath,

    [bool]$AttentionTraceSupported = $false,

    [string]$AttentionTracePath,

    [bool]$DisableDiffusionFlashAttention = $false
  )

  if ($TraceLevel -in @("h6", "h7") -and [string]::IsNullOrWhiteSpace($TraceDirectory)) {
    throw "TraceDirectory is required for H6/H7 capture"
  }
  if ($LatentTraceSupported -and [string]::IsNullOrWhiteSpace($LatentTracePath)) {
    throw "LatentTracePath is required when native latent trace is enabled"
  }
  if ($AttentionTraceSupported -and [string]::IsNullOrWhiteSpace($AttentionTracePath)) {
    throw "AttentionTracePath is required when native H7 attention trace is enabled"
  }

  $vramText = $MaxVramGb.ToString("0.0", [Globalization.CultureInfo]::InvariantCulture)
  $arguments = @(
    "-m", [string]$Request.model_path,
    "-p", [string]$Request.prompt,
    "-n", [string]$Request.negative,
    "-s", [string]$Request.seed,
    "--steps", [string]$Request.steps,
    "--cfg-scale", [string]$Request.cfg,
    "-W", [string]$Request.width,
    "-H", [string]$Request.height,
    "--sampling-method", [string]$Request.sampling_method,
    "--scheduler", [string]$Request.scheduler,
    "--backend", "cuda",
    "--max-vram", $vramText,
    "--offload-to-cpu",
    "--metadata-format", "json",
    "-o", $OutputPath
  )

  $flashAttention = -not $DisableDiffusionFlashAttention
  if ($flashAttention) {
    $arguments += "--diffusion-fa"
  }

  if ($TraceLevel -in @("h6", "h7")) {
    $arguments += @(
      "--preview", "proj",
      "--preview-interval", "1",
      "--preview-path", (Join-Path $TraceDirectory "latent-step-%03d.png")
    )
    if ($LatentTraceSupported) {
      $arguments += @("--latent-trace-path", $LatentTracePath)
    }
    if ($TraceLevel -eq "h7" -and $AttentionTraceSupported) {
      $arguments += @("--attention-trace-path", $AttentionTracePath)
    }
  }

  return [pscustomobject]@{
    Arguments = [string[]]$arguments
    FlashAttention = $flashAttention
  }
}

Export-ModuleMember -Function Get-DreamCachedFileHash, New-DreamStableDiffusionArguments
