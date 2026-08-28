[CmdletBinding()]
param()
$ErrorActionPreference='Stop'
Set-StrictMode -Version 2
$root=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$project=Join-Path $root 'tests\infrastructure\MLLM.Workbench.Infrastructure.Tests\MLLM.Workbench.Infrastructure.Tests.csproj'
& dotnet test $project -c Release --filter BackendSnapshotTests --no-restore
if($LASTEXITCODE -ne 0){throw "BackendSnapshotTests failed with rc=$LASTEXITCODE"}
Write-Host 'WORKBENCH_BACKEND_SNAPSHOT=PASS dashboard=PASS doctor=PASS installer=PASS readonly=PASS'
