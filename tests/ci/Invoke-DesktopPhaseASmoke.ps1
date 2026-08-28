[CmdletBinding()]
param()

$ErrorActionPreference='Stop'
Set-StrictMode -Version 2

$root=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$packageScript=Join-Path $root 'ci\package_desktop_phase_a.ps1'
$backendTestProject=Join-Path $root 'tests\infrastructure\MLLM.Workbench.Infrastructure.Tests\MLLM.Workbench.Infrastructure.Tests.csproj'
if(-not(Test-Path -LiteralPath $packageScript -PathType Leaf)){throw "Desktop package script missing: $packageScript"}
if(-not(Test-Path -LiteralPath $backendTestProject -PathType Leaf)){throw "Backend test project missing: $backendTestProject"}

function Get-FileFingerprint {
    param([Parameter(Mandatory=$true)][string]$Path)
    $exists=Test-Path -LiteralPath $Path -PathType Leaf
    return [pscustomobject]@{
        path=$Path
        exists=[bool]$exists
        sha256=if($exists){(Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()}else{$null}
    }
}

function Assert-FingerprintUnchanged {
    param($Before,$After,[string]$Name)
    if([bool]$Before.exists -ne [bool]$After.exists){throw "$Name existence changed during non-installing E2E"}
    if([string]$Before.sha256 -ne [string]$After.sha256){throw "$Name SHA256 changed during non-installing E2E"}
}

$outputRoot=Join-Path $env:RUNNER_TEMP ('mllm phase a e2e package '+[guid]::NewGuid().ToString('N'))
$extractRoot=Join-Path $env:RUNNER_TEMP ('mllm phase a e2e extract '+[guid]::NewGuid().ToString('N'))
$guiDataRoot=Join-Path $env:RUNNER_TEMP ('mllm phase a gui preflight '+[guid]::NewGuid().ToString('N'))

$installerStatePath=Join-Path $env:ProgramData 'M-LLM\Installer\state\installer_state.json'
$currentPointerPath=Join-Path $env:ProgramData 'M-LLM\Workbench\current.json'
$stateBefore=Get-FileFingerprint -Path $installerStatePath
$pointerBefore=Get-FileFingerprint -Path $currentPointerPath

try{
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $packageScript -OutputRoot $outputRoot
    if($LASTEXITCODE -ne 0){throw "Desktop packaging failed rc=$LASTEXITCODE"}

    $zip=Join-Path $outputRoot 'MLLM_WORKBENCH_DESKTOP_PHASE_A_win-x64.zip'
    $shaFile=$zip+'.sha256'
    if(-not(Test-Path -LiteralPath $zip -PathType Leaf)){throw "Desktop package ZIP missing: $zip"}
    if(-not(Test-Path -LiteralPath $shaFile -PathType Leaf)){throw "Desktop package SHA file missing: $shaFile"}
    $expected=((Get-Content -LiteralPath $shaFile -Raw).Trim() -split '\s+')[0].ToLowerInvariant()
    $actual=(Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant()
    if($expected -ne $actual){throw "Desktop package SHA256 mismatch expected=$expected actual=$actual"}

    Expand-Archive -LiteralPath $zip -DestinationPath $extractRoot -Force

    # Recreate a raw Safe Core foundation inside the extracted package. The
    # bootstrap must restore engine/gui from the verified overlay even when
    # the workbench is installed under a path containing spaces.
    Get-ChildItem -LiteralPath $extractRoot -Force -File -ErrorAction SilentlyContinue |
        Where-Object {$_.Name -like '.safe-core-materialized-*.stamp'} |
        Remove-Item -Force -ErrorAction Stop
    foreach($relativeDir in @('engine','gui')){
        $target=Join-Path $extractRoot $relativeDir
        if(Test-Path -LiteralPath $target -PathType Container){Remove-Item -LiteralPath $target -Recurse -Force}
    }

    $bootstrap=Join-Path $extractRoot 'Bootstrap_SafeCore.ps1'
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $bootstrap -ProjectRoot $extractRoot
    if($LASTEXITCODE -ne 0){throw "Raw Safe Core bootstrap failed rc=$LASTEXITCODE"}
    foreach($relative in @('engine\Core.psm1','gui\GuiAdapter.psm1')){
        if(-not(Test-Path -LiteralPath (Join-Path $extractRoot $relative) -PathType Leaf)){throw "Bootstrap did not restore: $relative"}
    }
    $stamps=@(Get-ChildItem -LiteralPath $extractRoot -Force -File | Where-Object {$_.Name -like '.safe-core-materialized-*.stamp'})
    if($stamps.Count -ne 1){throw "Bootstrap materialization stamp count is invalid: $($stamps.Count)"}

    # Packaged Desktop smoke uses the same BackendProcessHost path as the real
    # application and performs a real authenticated backend ping without a UI.
    $desktopExe=Join-Path $extractRoot 'desktop\MLLM.Workbench.Desktop.exe'
    if(-not(Test-Path -LiteralPath $desktopExe -PathType Leaf)){throw "Packaged desktop executable missing: $desktopExe"}
    $desktop=Start-Process -FilePath $desktopExe -ArgumentList @('--smoke') -PassThru
    if(-not $desktop.WaitForExit(60000)){
        try{$desktop.Kill()}catch{}
        throw 'Packaged Desktop --smoke exceeded 60 seconds'
    }
    if($desktop.ExitCode -ne 0){throw "Packaged Desktop --smoke failed rc=$($desktop.ExitCode)"}

    # Non-installing preflight must remain read-only and offline.
    $guiPreflight=Join-Path $extractRoot 'M_LLM_GUI_PREFLIGHT.ps1'
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $guiPreflight -DataRoot $guiDataRoot -NetworkMode OFFLINE_CACHE
    if($LASTEXITCODE -ne 0){throw "Packaged GUI preflight failed rc=$LASTEXITCODE"}
    $guiReportPath=Join-Path $guiDataRoot 'gui_preflight.json'
    if(-not(Test-Path -LiteralPath $guiReportPath -PathType Leaf)){throw 'GUI preflight report missing'}
    $guiReport=Get-Content -LiteralPath $guiReportPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if([string]$guiReport.status -ne 'PASS'){throw "GUI preflight report status is not PASS: $($guiReport.status)"}
    if([bool]$guiReport.core_install_authorized){throw 'GUI preflight unexpectedly authorized Core installation'}
    if([int]$guiReport.install_actions_executed -ne 0){throw 'GUI preflight executed installation actions'}
    if([int]$guiReport.network_actions_executed -ne 0){throw 'GUI preflight executed network actions'}

    # Exercise dashboard/doctor/installer snapshots against the EXTRACTED
    # package using the same BackendProcessHost + NamedPipeBackendClient that
    # the Desktop application uses. Do not maintain a second hand-written
    # process/pipe implementation in the E2E test.
    $oldBackendRoot=$env:MLLM_BACKEND_TEST_PROJECT_ROOT
    $env:MLLM_BACKEND_TEST_PROJECT_ROOT=$extractRoot
    try{
        & dotnet test $backendTestProject -c Release --no-restore --filter BackendSnapshotTests
        if($LASTEXITCODE -ne 0){throw "Packaged backend snapshot test failed rc=$LASTEXITCODE"}
    }finally{
        if($null -eq $oldBackendRoot){Remove-Item Env:MLLM_BACKEND_TEST_PROJECT_ROOT -ErrorAction SilentlyContinue}else{$env:MLLM_BACKEND_TEST_PROJECT_ROOT=$oldBackendRoot}
    }

    # Verify desktop-first and explicit legacy launch selection from the same
    # extracted package without starting a user-facing window.
    $oldLauncherTest=$env:MLLM_LAUNCHER_TEST
    $env:MLLM_LAUNCHER_TEST='1'
    try{
        $launcher=Join-Path $extractRoot 'Start_M_LLM_Workbench.cmd'
        $desktopTarget=@(& $launcher 2>&1 | ForEach-Object {[string]$_}) -join "`n"
        if($LASTEXITCODE -ne 0 -or $desktopTarget -notmatch 'MLLM_LAUNCH_TARGET=DESKTOP'){throw "Launcher did not select Desktop: $desktopTarget"}
        $legacyTarget=@(& $launcher --legacy 2>&1 | ForEach-Object {[string]$_}) -join "`n"
        if($LASTEXITCODE -ne 0 -or $legacyTarget -notmatch 'MLLM_LAUNCH_TARGET=LEGACY'){throw "Launcher did not select Legacy: $legacyTarget"}
    }finally{
        if($null -eq $oldLauncherTest){Remove-Item Env:MLLM_LAUNCHER_TEST -ErrorAction SilentlyContinue}else{$env:MLLM_LAUNCHER_TEST=$oldLauncherTest}
    }

    $stateAfter=Get-FileFingerprint -Path $installerStatePath
    $pointerAfter=Get-FileFingerprint -Path $currentPointerPath
    Assert-FingerprintUnchanged -Before $stateBefore -After $stateAfter -Name 'installer_state.json'
    Assert-FingerprintUnchanged -Before $pointerBefore -After $pointerAfter -Name 'current.json'

    Write-Host "DESKTOP_PHASE_A_E2E=PASS package_sha256=$actual bootstrap=PASS desktop_smoke=PASS gui_preflight=PASS snapshots=PASS launcher=PASS installer_state_readonly=PASS"
}finally{
    Remove-Item -LiteralPath $guiDataRoot,$extractRoot,$outputRoot -Recurse -Force -ErrorAction SilentlyContinue
}
