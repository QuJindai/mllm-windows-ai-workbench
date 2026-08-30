[CmdletBinding()]
param(
    [string]$OutputRoot=''
)

$ErrorActionPreference='Stop'
Set-StrictMode -Version 2
$root=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$packager=Join-Path $root 'ci\package_c7_release.ps1'
if(-not(Test-Path -LiteralPath $packager -PathType Leaf)){throw "C7 release package script missing: $packager"}
if(-not $OutputRoot){$OutputRoot=Join-Path $root 'artifacts\c7-release'}
$OutputRoot=[IO.Path]::GetFullPath($OutputRoot)

$installerName='MLLM_WORKBENCH_C7_OFFLINE_INSTALLER_win-x64.zip'
$portableName='MLLM_WORKBENCH_C7_PORTABLE_win-x64.zip'
$installerZip=Join-Path $OutputRoot $installerName
$portableZip=Join-Path $OutputRoot $portableName
$extractRoot=Join-Path $env:RUNNER_TEMP ('mllm c7 release extract '+[guid]::NewGuid().ToString('N'))
$fakeRoot=Join-Path $env:RUNNER_TEMP ('mllm c7 installed '+[guid]::NewGuid().ToString('N'))

$oldProgramFiles=$env:ProgramFiles
$oldProgramData=$env:ProgramData
$oldUserProfile=$env:USERPROFILE

function Assert-ShaSidecar {
    param([Parameter(Mandatory=$true)][string]$ZipPath)
    $sidecar=$ZipPath+'.sha256'
    if(-not(Test-Path -LiteralPath $ZipPath -PathType Leaf)){throw "Release ZIP missing: $ZipPath"}
    if(-not(Test-Path -LiteralPath $sidecar -PathType Leaf)){throw "Release SHA sidecar missing: $sidecar"}
    $expected=((Get-Content -LiteralPath $sidecar -Raw).Trim() -split '\s+')[0].ToLowerInvariant()
    $actual=(Get-FileHash -LiteralPath $ZipPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if($expected -ne $actual){throw "Release SHA mismatch file=$ZipPath expected=$expected actual=$actual"}
    return $actual
}

try{
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $packager -OutputRoot $OutputRoot -SourceSha ([string]$env:GITHUB_SHA)
    if($LASTEXITCODE -ne 0){throw "C7 release packaging failed rc=$LASTEXITCODE"}

    $installerSha=Assert-ShaSidecar -ZipPath $installerZip
    $portableSha=Assert-ShaSidecar -ZipPath $portableZip

    New-Item -ItemType Directory -Force -Path $extractRoot | Out-Null
    Expand-Archive -LiteralPath $installerZip -DestinationPath $extractRoot -Force
    foreach($relative in @(
        'INSTALL_M_LLM_C7.cmd',
        'installer\Install-C7Bundle.ps1',
        'installer\Start-UniversalInstaller.ps1',
        'config\source-manifest.json',
        ('payload\'+$portableName),
        ('payload\'+$portableName+'.sha256'),
        'RELEASE_INFO.txt'
    )){
        $full=Join-Path $extractRoot $relative
        if(-not(Test-Path -LiteralPath $full -PathType Leaf)){throw "Offline installer bundle missing required file: $relative"}
    }

    $portableInspectRoot=Join-Path $extractRoot 'portable-inspect'
    New-Item -ItemType Directory -Force -Path $portableInspectRoot | Out-Null
    Expand-Archive -LiteralPath (Join-Path $extractRoot ('payload\'+$portableName)) -DestinationPath $portableInspectRoot -Force
    foreach($relative in @(
        'runtime\WorkbenchBackend.ps1',
        'runtime\WorkbenchRuntimeAdapter.psm1',
        'runtime\WorkbenchRuntimeLifecycle.ps1'
    )){
        $full=Join-Path $portableInspectRoot $relative
        if(-not(Test-Path -LiteralPath $full -PathType Leaf)){throw "C7 portable runtime dependency missing: $relative"}
    }

    $env:ProgramFiles=Join-Path $fakeRoot 'Program Files'
    $env:ProgramData=Join-Path $fakeRoot 'ProgramData'
    $env:USERPROFILE=Join-Path $fakeRoot 'User'
    foreach($dir in @($env:ProgramFiles,$env:ProgramData,$env:USERPROFILE)){
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
    }

    $versionId='c7-knowledge-microscope-20260830'
    $installScript=Join-Path $extractRoot 'installer\Install-C7Bundle.ps1'
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $installScript -NoElevate -NoLaunch -VersionId $versionId
    if($LASTEXITCODE -ne 0){throw "C7 offline install failed rc=$LASTEXITCODE"}

    $pointerPath=Join-Path $env:ProgramData 'M-LLM\Workbench\current.json'
    if(-not(Test-Path -LiteralPath $pointerPath -PathType Leaf)){throw "Installed current pointer missing: $pointerPath"}
    $pointer=Get-Content -LiteralPath $pointerPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if([string]$pointer.version_id -ne $versionId){throw "Activated version mismatch expected=$versionId actual=$($pointer.version_id)"}
    $installedRoot=[IO.Path]::GetFullPath([string]$pointer.version_path)
    foreach($relative in @(
        'runtime\WorkbenchBackend.ps1',
        'runtime\WorkbenchRuntimeAdapter.psm1',
        'runtime\WorkbenchRuntimeLifecycle.ps1'
    )){
        $full=Join-Path $installedRoot $relative
        if(-not(Test-Path -LiteralPath $full -PathType Leaf)){throw "Installed runtime dependency missing: $relative"}
    }

    $installedExe=Join-Path $installedRoot 'desktop\MLLM.Workbench.Desktop.exe'
    if(-not(Test-Path -LiteralPath $installedExe -PathType Leaf)){throw "Installed desktop executable missing: $installedExe"}

    $process=Start-Process -FilePath $installedExe -ArgumentList @('--smoke') -WorkingDirectory (Split-Path -Parent $installedExe) -PassThru
    if(-not $process.WaitForExit(60000)){
        try{$process.Kill()}catch{}
        throw 'Installed C7 desktop --smoke exceeded 60 seconds'
    }
    if($process.ExitCode -ne 0){throw "Installed C7 desktop --smoke failed rc=$($process.ExitCode)"}

    $installerBytes=(Get-Item -LiteralPath $installerZip).Length
    $portableBytes=(Get-Item -LiteralPath $portableZip).Length
    Write-Host "C7_RELEASE_INSTALL_SMOKE=PASS version=$versionId installer_bytes=$installerBytes installer_sha256=$installerSha portable_bytes=$portableBytes portable_sha256=$portableSha runtime_complete=PASS activated=PASS installed_desktop_smoke=PASS"
}finally{
    $env:ProgramFiles=$oldProgramFiles
    $env:ProgramData=$oldProgramData
    $env:USERPROFILE=$oldUserProfile
    Remove-Item -LiteralPath $extractRoot -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $fakeRoot -Recurse -Force -ErrorAction SilentlyContinue
}
