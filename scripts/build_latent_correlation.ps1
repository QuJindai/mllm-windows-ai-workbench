[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$SourceDirectory,
    [Parameter(Mandatory = $true)][string]$BuildDirectory,
    [string]$Root = 'E:\Dream',
    [int]$Parallel = 2
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'set_dream_build_env.ps1') -Root $Root
$sourcePath = (Resolve-Path -LiteralPath $SourceDirectory).Path
$buildPath = (Resolve-Path -LiteralPath $BuildDirectory).Path
$cache = Get-Content -Raw -LiteralPath (Join-Path $buildPath 'CMakeCache.txt')
$cmakeSource = ($sourcePath -replace '\\', '/').TrimEnd('/')
if ($cache -notmatch ('(?m)^CMAKE_HOME_DIRECTORY:INTERNAL=' + [regex]::Escape($cmakeSource) + '\r?$')) {
    throw 'Build cache does not belong to the requested native source tree.'
}
$runPath = Join-Path $Root ('test-runs\latent-correlation-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
New-Item -ItemType Directory -Path $runPath | Out-Null
$testExe = Join-Path $runPath 'test-latent-correlation.exe'
$testObj = Join-Path $runPath 'test-latent-correlation.obj'
$compileLog = Join-Path $runPath 'cpu-compile.log'
& cl.exe /nologo /EHsc /std:c++17 "/I$sourcePath\examples\cli" "/I$sourcePath\thirdparty" `
    (Join-Path $sourcePath 'tests\test_latent_correlation.cpp') "/Fe:$testExe" "/Fo:$testObj" *> $compileLog
if ($LASTEXITCODE -ne 0) { Get-Content -LiteralPath $compileLog -Tail 40; throw 'CPU writer test compilation failed.' }
& $testExe (Join-Path $runPath 'fixtures') *> (Join-Path $runPath 'cpu-test.log')
if ($LASTEXITCODE -ne 0) { Get-Content (Join-Path $runPath 'cpu-test.log'); throw 'CPU writer test failed.' }
Get-Content (Join-Path $runPath 'cpu-test.log')
$deltaExe = Join-Path $runPath 'test-latent-delta.exe'
$deltaObj = Join-Path $runPath 'test-latent-delta.obj'
& cl.exe /nologo /EHsc /std:c++17 "/I$sourcePath\examples\cli" "/I$sourcePath\thirdparty" `
    (Join-Path $sourcePath 'tests\test_latent_delta.cpp') "/Fe:$deltaExe" "/Fo:$deltaObj" *> (Join-Path $runPath 'delta-compile.log')
if ($LASTEXITCODE -ne 0) { Get-Content (Join-Path $runPath 'delta-compile.log') -Tail 40; throw 'CPU delta test compilation failed.' }
& $deltaExe (Join-Path $runPath 'delta-fixtures') *> (Join-Path $runPath 'delta-test.log')
if ($LASTEXITCODE -ne 0) { Get-Content (Join-Path $runPath 'delta-test.log'); throw 'CPU delta writer test failed.' }
Get-Content (Join-Path $runPath 'delta-test.log')
$buildLog = Join-Path $runPath 'native-build.log'
Write-Host "Native compile only; logs: $runPath"
& cmake.exe --build $buildPath --config Release --target sd-cli --parallel $Parallel *> $buildLog
if ($LASTEXITCODE -ne 0) { Get-Content -LiteralPath $buildLog -Tail 60; throw 'Native CLI build failed.' }
Get-Content -LiteralPath $buildLog -Tail 8
$binary = Join-Path $buildPath 'bin\sd-cli.exe'
if (-not (Test-Path -LiteralPath $binary -PathType Leaf)) { throw 'Built CLI is missing.' }
Get-FileHash -LiteralPath $binary
Write-Host "BUILT_CLI=$binary"
Write-Host "EVIDENCE=$runPath"
Write-Host 'No GPU runtime executed; no binaries installed or activated.'
