param([string]$Root = 'E:\Dream')
$ErrorActionPreference = 'Stop'
$vsDev = Join-Path $Root 'tools\vs2022\Common7\Tools\VsDevCmd.bat'
if (-not (Test-Path -LiteralPath $vsDev)) { throw "Install the E: C++ Build Tools first: $vsDev" }
$command = '"' + $vsDev + '" -no_logo -arch=x64 -host_arch=x64 >nul && set'
$variables = & cmd.exe /d /s /c $command
if ($LASTEXITCODE -ne 0) { throw 'Could not initialize MSVC x64 build environment.' }
foreach ($line in $variables) {
    if ($line -match '^([^=]+)=(.*)$') { [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2], 'Process') }
}
$env:CUDA_PATH = Join-Path $Root 'tools\cuda\12.9.1'
$env:CUDAToolkit_ROOT = $env:CUDA_PATH
$env:CUDA_PATH_V12_9 = $env:CUDA_PATH
$env:TEMP = Join-Path $Root 'temp'
$env:TMP = $env:TEMP
$env:Path = "$env:CUDA_PATH\bin;$Root\tools\cmake\cmake-4.4.3-windows-x86_64\bin;$Root\tools\ninja;$env:Path"
