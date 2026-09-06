$ErrorActionPreference = "Stop"

try {
  $Nvidia = @(nvidia-smi --query-gpu=name,memory.total,memory.free,driver_version --format=csv,noheader,nounits 2>$null)
  if ($LASTEXITCODE -ne 0 -or $Nvidia.Count -eq 0 -or [string]::IsNullOrWhiteSpace([string]$Nvidia[0])) {
    throw "nvidia-smi returned no GPU data"
  }

  Write-Host ([string]$Nvidia[0])
  Write-Host "CUDA_VISIBLE_PASS"
}
catch {
  Write-Host "CUDA_VISIBLE_FAIL"
  Write-Error $_
  exit 2
}

