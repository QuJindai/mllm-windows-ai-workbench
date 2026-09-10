[CmdletBinding()]
param([string]$Root = 'E:\Dream', [int]$Parallel = 4)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'set_dream_build_env.ps1') -Root $Root
$source = Join-Path $Root 'src\stable-diffusion.cpp'
$build = Join-Path $Root 'builds\stable-diffusion-cuda-12.9.1-latent'
$release = Join-Path $Root 'app\stable-diffusion-cuda-12.9.1-latent'
New-Item -ItemType Directory -Path $build -Force | Out-Null
$probe = Join-Path $build 'cuda-probe.exe'
& nvcc.exe -arch=sm_89 -O2 (Join-Path $PSScriptRoot 'probes\cuda_probe.cu') -o $probe
if ($LASTEXITCODE -ne 0) { throw 'CUDA probe compilation failed.' }
& $probe
if ($LASTEXITCODE -ne 0) { throw 'CUDA hardware execution probe failed.' }
$configure = @('-S', $source, '-B', $build, '-G', 'Ninja', '-DCMAKE_BUILD_TYPE=Release', '-DCMAKE_C_COMPILER=cl', '-DCMAKE_CXX_COMPILER=cl', '-DCMAKE_CXX_FLAGS=/DWIN32 /D_WINDOWS /W3 /GR /EHsc /bigobj', "-DCMAKE_CUDA_COMPILER=$env:CUDA_PATH\bin\nvcc.exe", "-DCUDAToolkit_ROOT=$env:CUDA_PATH", '-DCMAKE_CUDA_ARCHITECTURES=89-real', '-DSD_CUDA=ON', '-DSD_BUILD_SHARED_LIBS=ON', '-DSD_BUILD_SHARED_GGML_LIB=ON', '-DSD_BUILD_EXAMPLES=ON')
& cmake.exe @configure
if ($LASTEXITCODE -ne 0) { throw 'CUDA engine configuration failed.' }
$buildLog = Join-Path $build 'build.log'
Write-Host "Compiling native CUDA engine. Detailed log: $buildLog"
& cmake.exe --build $build --config Release --target sd-cli sd-server --parallel $Parallel *> $buildLog
if ($LASTEXITCODE -ne 0) { Get-Content -LiteralPath $buildLog -Tail 60; throw 'CUDA engine compilation failed.' }
New-Item -ItemType Directory -Path $release -Force | Out-Null
Get-ChildItem -LiteralPath (Join-Path $build 'bin') -File | Where-Object { $_.Extension -in @('.exe', '.dll') } | Copy-Item -Destination $release -Force
foreach ($dll in @('cudart64_12.dll','cublas64_12.dll','cublasLt64_12.dll')) {
    Copy-Item -LiteralPath (Join-Path $env:CUDA_PATH "bin\$dll") -Destination $release -Force
}
$engine = Join-Path $release 'sd-cli.exe'
$server = Join-Path $release 'sd-server.exe'
$helpText = & $engine --help 2>&1 | Out-String
if ($LASTEXITCODE -ne 0 -or $helpText -notmatch '--latent-trace-path') { throw 'Built engine did not pass latent trace capability check.' }
if (-not (Test-Path -LiteralPath $server -PathType Leaf)) { throw 'Built persistent server executable is missing.' }
$files = @(Get-ChildItem -LiteralPath $release -File | Where-Object { $_.Extension -in @('.exe','.dll') } | ForEach-Object { [pscustomobject]@{name=$_.Name;sha256=(Get-FileHash -LiteralPath $_.FullName).Hash;bytes=$_.Length} })
[pscustomobject]@{builtAt=(Get-Date -Format o);sourceRevision=(& git.exe -C $source rev-parse HEAD);cuda='12.9.1';architecture='sm_89';latentTrace=$true;files=$files} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $release 'build-manifest.json') -Encoding utf8
Write-Host "DREAM_CUDA_ENGINE_BUILT=$engine"
Write-Host "DREAM_CUDA_SERVER_BUILT=$server"
Write-Host 'Activation requires a successful generation check; the current engine has not been changed.'
