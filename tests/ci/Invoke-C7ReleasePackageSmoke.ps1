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
$tempRoot=if([string]::IsNullOrWhiteSpace($env:RUNNER_TEMP)){[IO.Path]::GetTempPath()}else{$env:RUNNER_TEMP}
$extractRoot=Join-Path $tempRoot ('mllm c7 release extract '+[guid]::NewGuid().ToString('N'))
$fakeRoot=Join-Path $tempRoot ('mllm c7 installed '+[guid]::NewGuid().ToString('N'))

$oldProgramFiles=$env:ProgramFiles
$oldProgramW6432=$env:ProgramW6432
$oldProgramFilesX86=${env:ProgramFiles(x86)}
$oldProgramData=$env:ProgramData
$oldUserProfile=$env:USERPROFILE
$oldSmokeDiagnostic=$env:MLLM_SMOKE_DIAGNOSTIC_PATH
$oldNetworkMode=$env:MLLM_NETWORK_MODE
$sourceSha=[string]$env:GITHUB_SHA
if([string]::IsNullOrWhiteSpace($sourceSha)){
    $sourceSha=([string](& git -C $root rev-parse HEAD 2>$null | Select-Object -First 1)).Trim()
}
if([string]::IsNullOrWhiteSpace($sourceSha)){throw 'Unable to resolve release source SHA.'}

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

function Invoke-InstalledDesktopSmoke {
    param(
        [Parameter(Mandatory=$true)][string]$Exe,
        [Parameter(Mandatory=$true)][string[]]$Arguments,
        [Parameter(Mandatory=$true)][string]$Name,
        [int]$TimeoutMs=60000,
        [switch]$CaptureDiagnostic
    )
    $diag=$null
    if($CaptureDiagnostic){
        $diag=Join-Path $tempRoot ('mllm-smoke-'+[guid]::NewGuid().ToString('N')+'.txt')
        $env:MLLM_SMOKE_DIAGNOSTIC_PATH=$diag
    }
    try{
        $process=Start-Process -FilePath $Exe -ArgumentList $Arguments -WorkingDirectory (Split-Path -Parent $Exe) -PassThru
        if(-not $process.WaitForExit($TimeoutMs)){
            try{$process.Kill()}catch{}
            $detail=if($diag -and (Test-Path -LiteralPath $diag -PathType Leaf)){Get-Content -LiteralPath $diag -Raw}else{'<no diagnostic file>'}
            throw "Installed C7 desktop $Name exceeded $TimeoutMs ms. diagnostic=$detail"
        }
        if($process.ExitCode -ne 0){
            $detail=if($diag -and (Test-Path -LiteralPath $diag -PathType Leaf)){Get-Content -LiteralPath $diag -Raw}else{'<no diagnostic file>'}
            throw "Installed C7 desktop $Name failed rc=$($process.ExitCode). diagnostic=$detail"
        }
    }finally{
        if($CaptureDiagnostic){
            if($null -eq $oldSmokeDiagnostic){Remove-Item Env:MLLM_SMOKE_DIAGNOSTIC_PATH -ErrorAction SilentlyContinue}else{$env:MLLM_SMOKE_DIAGNOSTIC_PATH=$oldSmokeDiagnostic}
            if($diag){Remove-Item -LiteralPath $diag -Force -ErrorAction SilentlyContinue}
        }
    }
}

try{
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $packager -OutputRoot $OutputRoot -SourceSha $sourceSha
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
        'runtime\WorkbenchRuntimeLifecycle.ps1',
        'web\backend\app.py',
        'web\backend\engine_bridge.py',
        'web\backend\requirements.txt'
    )){
        $full=Join-Path $portableInspectRoot $relative
        if(-not(Test-Path -LiteralPath $full -PathType Leaf)){throw "C7 portable runtime dependency missing: $relative"}
    }

    $env:ProgramFiles=Join-Path $fakeRoot 'Program Files'
    $env:ProgramW6432=$env:ProgramFiles
    ${env:ProgramFiles(x86)}=$env:ProgramFiles
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
        'runtime\WorkbenchRuntimeLifecycle.ps1',
        'web\backend\app.py',
        'web\backend\engine_bridge.py',
        'web\backend\requirements.txt'
    )){
        $full=Join-Path $installedRoot $relative
        if(-not(Test-Path -LiteralPath $full -PathType Leaf)){throw "Installed runtime dependency missing: $relative"}
    }

    $installedExe=Join-Path $installedRoot 'desktop\MLLM.Workbench.Desktop.exe'
    if(-not(Test-Path -LiteralPath $installedExe -PathType Leaf)){throw "Installed desktop executable missing: $installedExe"}

    # Release smoke remains network-isolated even though normal product startup may use AUTO_CN_FIRST.
    $env:MLLM_NETWORK_MODE='OFFLINE_CACHE'
    Invoke-InstalledDesktopSmoke -Exe $installedExe -Arguments @('--smoke') -Name '--smoke' -TimeoutMs 60000
    Invoke-InstalledDesktopSmoke -Exe $installedExe -Arguments @('--smoke-knowledge') -Name '--smoke-knowledge' -TimeoutMs 20000 -CaptureDiagnostic
    Invoke-InstalledDesktopSmoke -Exe $installedExe -Arguments @('--smoke-d1-navigation') -Name '--smoke-d1-navigation' -TimeoutMs 30000 -CaptureDiagnostic
    Invoke-InstalledDesktopSmoke -Exe $installedExe -Arguments @('--smoke-d2-navigation') -Name '--smoke-d2-navigation' -TimeoutMs 30000 -CaptureDiagnostic

    $installerBytes=(Get-Item -LiteralPath $installerZip).Length
    $portableBytes=(Get-Item -LiteralPath $portableZip).Length
    Write-Host "C7_RELEASE_INSTALL_SMOKE=PASS version=$versionId installer_bytes=$installerBytes installer_sha256=$installerSha portable_bytes=$portableBytes portable_sha256=$portableSha runtime_complete=PASS web_runtime_complete=PASS activated=PASS installed_desktop_smoke=PASS knowledge_navigation_smoke=PASS d1_navigation_smoke=PASS d2_navigation_smoke=PASS smoke_network_mode=OFFLINE_CACHE"
}finally{
    $env:ProgramFiles=$oldProgramFiles
    if($null -eq $oldProgramW6432){Remove-Item Env:ProgramW6432 -ErrorAction SilentlyContinue}else{$env:ProgramW6432=$oldProgramW6432}
    if($null -eq $oldProgramFilesX86){Remove-Item 'Env:ProgramFiles(x86)' -ErrorAction SilentlyContinue}else{${env:ProgramFiles(x86)}=$oldProgramFilesX86}
    $env:ProgramData=$oldProgramData
    $env:USERPROFILE=$oldUserProfile
    if($null -eq $oldSmokeDiagnostic){Remove-Item Env:MLLM_SMOKE_DIAGNOSTIC_PATH -ErrorAction SilentlyContinue}else{$env:MLLM_SMOKE_DIAGNOSTIC_PATH=$oldSmokeDiagnostic}
    if($null -eq $oldNetworkMode){Remove-Item Env:MLLM_NETWORK_MODE -ErrorAction SilentlyContinue}else{$env:MLLM_NETWORK_MODE=$oldNetworkMode}
    Remove-Item -LiteralPath $extractRoot -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $fakeRoot -Recurse -Force -ErrorAction SilentlyContinue
}
