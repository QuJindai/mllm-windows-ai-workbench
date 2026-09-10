param([string]$Root = 'E:\Dream', [switch]$Compile)
$ErrorActionPreference = "Stop"
$cudaVisible = $false

try {
  $Nvidia = @(nvidia-smi --query-gpu=name,memory.total,memory.free,driver_version --format=csv,noheader,nounits 2>$null)
  if ($LASTEXITCODE -ne 0 -or $Nvidia.Count -eq 0 -or [string]::IsNullOrWhiteSpace([string]$Nvidia[0])) {
    throw "nvidia-smi returned no GPU data"
  }

  Write-Host ([string]$Nvidia[0])
  Write-Host "CUDA_VISIBLE_PASS"
  $cudaVisible = $true
  $toolkit = Join-Path $Root 'tools\cuda\12.9.1'
  foreach ($file in @('bin\nvcc.exe','include\cuda_runtime.h','lib\x64\cudart.lib','lib\x64\cublas.lib')) {
    if (-not (Test-Path -LiteralPath (Join-Path $toolkit $file))) { throw "CUDA Toolkit missing $file" }
  }
  & (Join-Path $toolkit 'bin\nvcc.exe') --version
  if ($LASTEXITCODE -ne 0) { throw 'CUDA compiler cannot start.' }
  Write-Host 'CUDA_TOOLKIT_PASS'
  if ($Compile) {
    . (Join-Path $PSScriptRoot 'set_dream_build_env.ps1') -Root $Root
    $probeDir = Join-Path $Root 'builds\cuda-toolchain-probe'
    New-Item -ItemType Directory -Path $probeDir -Force | Out-Null
    & nvcc.exe -arch=sm_89 -O2 (Join-Path $PSScriptRoot 'probes\cuda_probe.cu') -o (Join-Path $probeDir 'cuda-probe.exe')
    if ($LASTEXITCODE -ne 0) { throw 'CUDA compilation probe failed.' }
    & (Join-Path $probeDir 'cuda-probe.exe')
    if ($LASTEXITCODE -ne 0) { throw 'CUDA kernel execution failed.' }
  }
}
catch {
  if (-not $cudaVisible) {
    Write-Host "CUDA_VISIBLE_FAIL"
  }
  Write-Host "CUDA_VERIFY_FAIL"
  Write-Error $_
  exit 2
}
