param(
  [string]$SourceDirectory = "E:\Dream\src\stable-diffusion.cpp-h7\build-h7-cuda-ninja\bin",
  [string]$DestinationDirectory = "E:\Dream\app\stable-diffusion-cuda-h7",
  [string]$CudaBinDirectory = "E:\Dream\tools\cuda\12.9.1\bin",
  [string]$SourceRevision = "6b3edaaf32cc19e5bb2d819c788bd557eddc8eba"
)

$ErrorActionPreference = "Stop"
$destination = [IO.Path]::GetFullPath($DestinationDirectory)
if (-not [string]::Equals($destination, "E:\Dream\app\stable-diffusion-cuda-h7", [StringComparison]::OrdinalIgnoreCase)) {
  throw "H7 package destination must be exactly E:\Dream\app\stable-diffusion-cuda-h7"
}

$source = [IO.Path]::GetFullPath($SourceDirectory)
$cudaBin = [IO.Path]::GetFullPath($CudaBinDirectory)
$files = @(
  @{ Source = Join-Path $source "sd-cli.exe"; Name = "sd-cli.exe" },
  @{ Source = Join-Path $source "stable-diffusion.dll"; Name = "stable-diffusion.dll" },
  @{ Source = Join-Path $cudaBin "cudart64_12.dll"; Name = "cudart64_12.dll" },
  @{ Source = Join-Path $cudaBin "cublas64_12.dll"; Name = "cublas64_12.dll" },
  @{ Source = Join-Path $cudaBin "cublasLt64_12.dll"; Name = "cublasLt64_12.dll" }
)
foreach ($file in $files) {
  if (-not (Test-Path -LiteralPath $file.Source -PathType Leaf)) {
    throw "Required H7 package file is missing: $($file.Source)"
  }
}

New-Item -ItemType Directory -Force -Path $destination | Out-Null
foreach ($file in $files) {
  Copy-Item -LiteralPath $file.Source -Destination (Join-Path $destination $file.Name) -Force
}

$helpText = (& (Join-Path $destination "sd-cli.exe") --help 2>&1 | Out-String)
if ($helpText -notmatch "--attention-trace-path" -or $helpText -notmatch '--conditioning-trace-path' -or $helpText -notmatch 'cross/self-attention') {
  throw "Packaged research engine is missing H6 or H7 trace capabilities"
}

$artifacts = @($files | ForEach-Object {
  $path = Join-Path $destination $_.Name
  $item = Get-Item -LiteralPath $path
  [ordered]@{
    name = $_.Name
    bytes = [int64]$item.Length
    sha256 = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
  }
})
$manifest = [ordered]@{
  schemaVersion = 1
  executable = "sd-cli.exe"
  capabilities = @("h7-attention-v1", "h7-self-attention-v1", "h6-conditioning-v1")
  source = "debug-unet"
  sourceRevision = $SourceRevision
  sourceTreeDirty = $true
  cudaToolkit = "12.9.1"
  cudaArchitecture = 89
  buildType = "Release"
  productionEngineUntouched = "E:\Dream\app\stable-diffusion-cuda-12.9.1-latent\sd-cli.exe"
  packagedAt = (Get-Date).ToUniversalTime().ToString("o")
  artifacts = $artifacts
}
$manifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $destination "build-manifest.json") -Encoding UTF8

Write-Output "DREAM_H7_PACKAGE_PASS"
Write-Output "destination=$destination"
Write-Output "capability=h7-attention-v1"
