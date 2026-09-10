[CmdletBinding()]
param([string]$Root = 'E:\Dream', [switch]$CudaOnly, [switch]$BuildToolsOnly)

$ErrorActionPreference = 'Stop'
$Root = [IO.Path]::GetFullPath($Root)
if (-not $Root.StartsWith('E:\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Install root must be on E:.' }
$download = Join-Path $Root 'cache\toolchain-downloads'
$stage = Join-Path $Root 'temp\toolchain-install'
$toolkit = Join-Path $Root 'tools\cuda\12.9.1'
foreach ($p in @($download, $stage, $toolkit)) { New-Item -ItemType Directory -Path $p -Force | Out-Null }
$env:TEMP = $stage
$env:TMP = $stage

if (-not $BuildToolsOnly) {
    $base = 'https://developer.download.nvidia.com/compute/cuda/redist/'
    $manifestPath = Join-Path $download 'redistrib_12.9.1.json'
    Invoke-WebRequest ($base + 'redistrib_12.9.1.json') -OutFile $manifestPath
    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    # NVIDIA's complete redistributable development/runtime components. IDE integration
    # and standalone GUI profilers are optional and are not required by the native engine.
    $excluded = @('nsight_compute', 'nsight_systems', 'nsight_vse', 'visual_studio_integration', 'cuda_nvvp')
    $components = @($manifest.PSObject.Properties | Where-Object { $_.Value.'windows-x86_64' -and $_.Name -notin $excluded })
    foreach ($component in $components) {
        $entry = $component.Value.'windows-x86_64'
        $zip = Join-Path $download ([IO.Path]::GetFileName($entry.relative_path))
        if (-not (Test-Path -LiteralPath $zip) -or (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash -ne $entry.sha256) {
            Write-Host "Downloading $($component.Name) $($component.Value.version)"
            & curl.exe --fail --location --retry 3 --silent --show-error --output $zip ($base + $entry.relative_path)
            if ($LASTEXITCODE -ne 0) { throw "Download failed: $($component.Name)" }
        }
        if ((Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash -ne $entry.sha256) { throw "SHA256 mismatch: $zip" }
        $receipt = Join-Path $toolkit ('receipts\' + $component.Name + '.json')
        if (Test-Path -LiteralPath $receipt) { Write-Host "Verified installed $($component.Name)"; continue }
        Write-Host "Installing $($component.Name) (SHA256 verified)"
        Expand-Archive -LiteralPath $zip -DestinationPath $stage -Force
        $unpacked = Join-Path $stage ([IO.Path]::GetFileNameWithoutExtension($zip))
        foreach ($item in Get-ChildItem -LiteralPath $unpacked) {
            if ($item.PSIsContainer) { Copy-Item -LiteralPath $item.FullName -Destination $toolkit -Recurse -Force }
        }
        $licenseDir = Join-Path $toolkit ('licenses\' + $component.Name)
        New-Item -ItemType Directory -Path $licenseDir -Force | Out-Null
        Get-ChildItem -LiteralPath $unpacked -File | Copy-Item -Destination $licenseDir -Force
        New-Item -ItemType Directory -Path (Split-Path $receipt) -Force | Out-Null
        [pscustomobject]@{component=$component.Name;version=$component.Value.version;url=$base+$entry.relative_path;sha256=$entry.sha256;installedAt=(Get-Date -Format o)} | ConvertTo-Json | Set-Content -LiteralPath $receipt -Encoding utf8
    }
    Copy-Item -LiteralPath $manifestPath -Destination (Join-Path $toolkit 'redistrib_12.9.1.json') -Force
    foreach ($required in @('bin\nvcc.exe', 'include\cuda_runtime.h', 'include\cublas_v2.h', 'lib\x64\cudart.lib', 'lib\x64\cublas.lib')) {
        if (-not (Test-Path -LiteralPath (Join-Path $toolkit $required))) { throw "Toolkit missing $required" }
    }
    Write-Host "CUDA_TOOLKIT_INSTALLED=$toolkit"
    [Environment]::SetEnvironmentVariable('CUDA_PATH', $toolkit, 'User')
    [Environment]::SetEnvironmentVariable('CUDA_PATH_V12_9', $toolkit, 'User')
    $userPath = @([Environment]::GetEnvironmentVariable('Path', 'User') -split ';' | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    $cudaBin = Join-Path $toolkit 'bin'
    if ($userPath -notcontains $cudaBin) { [Environment]::SetEnvironmentVariable('Path', (($userPath + $cudaBin) -join ';'), 'User') }
}

if (-not $CudaOnly) {
    $installer = Join-Path $download 'vs_buildtools_2022.exe'
    $vsRoot = Join-Path $Root 'tools\vs2022'
    Invoke-WebRequest 'https://aka.ms/vs/17/release/vs_buildtools.exe' -OutFile $installer
    $signature = Get-AuthenticodeSignature -LiteralPath $installer
    if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Microsoft Corporation') { throw 'Invalid Microsoft installer signature.' }
    $args = @('--quiet', '--wait', '--norestart', '--nocache', '--installPath', $vsRoot, '--path', ('cache=' + (Join-Path $Root 'cache\vs-packages')), '--add', 'Microsoft.VisualStudio.Component.VC.Tools.x86.x64')
    $process = Start-Process -FilePath $installer -ArgumentList $args -WindowStyle Hidden -Wait -PassThru
    if ($process.ExitCode -notin @(0,3010)) { throw "Build Tools installation failed: $($process.ExitCode). See $stage\dd_* logs." }
    Write-Host "MSVC_INSTALLED=$vsRoot (exit=$($process.ExitCode))"
}
