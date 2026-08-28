[CmdletBinding()]
param(
    [string]$OutputRoot='',
    [ValidateSet('Debug','Release')][string]$Configuration='Release'
)

$ErrorActionPreference='Stop'
Set-StrictMode -Version 2
$root=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if(-not $OutputRoot){$OutputRoot=Join-Path $root 'artifacts'}
$OutputRoot=[IO.Path]::GetFullPath($OutputRoot)
if(-not(Test-Path -LiteralPath $OutputRoot -PathType Container)){New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null}
$stage=Join-Path $OutputRoot ('desktop-phase-a-stage-'+[guid]::NewGuid().ToString('N'))
$zip=Join-Path $OutputRoot 'MLLM_WORKBENCH_DESKTOP_PHASE_A_win-x64.zip'
$shaFile=$zip+'.sha256'

function Copy-RequiredFile {
    param([string]$Relative)
    $source=Join-Path $root $Relative
    if(-not(Test-Path -LiteralPath $source -PathType Leaf)){throw "Required package source file missing: $Relative"}
    $destination=Join-Path $stage $Relative
    $parent=Split-Path -Parent $destination
    if(-not(Test-Path -LiteralPath $parent -PathType Container)){New-Item -ItemType Directory -Force -Path $parent | Out-Null}
    Copy-Item -LiteralPath $source -Destination $destination -Force
}

try{
    New-Item -ItemType Directory -Force -Path $stage | Out-Null
    foreach($relative in @(
        'Bootstrap_SafeCore.ps1',
        'Start_M_LLM_Workbench.cmd',
        'Start_M_LLM_Workbench.ps1',
        'M_LLM_GUI_PREFLIGHT.ps1',
        'M_LLM_PHYSICAL_PREFLIGHT.ps1',
        'runtime\WorkbenchBackend.ps1'
    )){Copy-RequiredFile -Relative $relative}

    foreach($dirName in @('installer','config')){
        $sourceDir=Join-Path $root $dirName
        if(-not(Test-Path -LiteralPath $sourceDir -PathType Container)){throw "Required package source directory missing: $dirName"}
        Copy-Item -LiteralPath $sourceDir -Destination $stage -Recurse -Force
    }
    $stageCi=Join-Path $stage 'ci'
    New-Item -ItemType Directory -Force -Path $stageCi | Out-Null
    $overlay=Join-Path $root 'ci\overlay'
    if(-not(Test-Path -LiteralPath $overlay -PathType Container)){throw 'Safe Core overlay directory missing'}
    Copy-Item -LiteralPath $overlay -Destination $stageCi -Recurse -Force

    # Materialize Safe Core before packaging. The installed version may live under Program Files
    # and the normal desktop process must not require write access to its own program directory.
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $stage 'Bootstrap_SafeCore.ps1') -ProjectRoot $stage
    if($LASTEXITCODE -ne 0){throw "Safe Core pre-materialization failed rc=$LASTEXITCODE"}
    foreach($relative in @('engine\Core.psm1','gui\GuiAdapter.psm1')){
        if(-not(Test-Path -LiteralPath (Join-Path $stage $relative) -PathType Leaf)){throw "Pre-materialized Safe Core file missing: $relative"}
    }
    $stamps=@(Get-ChildItem -LiteralPath $stage -Force -File | Where-Object { $_.Name -like '.safe-core-materialized-*.stamp' })
    if($stamps.Count -ne 1){throw "Expected one Safe Core materialization stamp, got $($stamps.Count)"}

    $desktop=Join-Path $stage 'desktop'
    New-Item -ItemType Directory -Force -Path $desktop | Out-Null
    & dotnet publish (Join-Path $root 'src\MLLM.Workbench.Desktop\MLLM.Workbench.Desktop.csproj') -c $Configuration -r win-x64 --self-contained true -o $desktop
    if($LASTEXITCODE -ne 0){throw "Desktop self-contained publish failed rc=$LASTEXITCODE"}
    $desktopExe=Join-Path $desktop 'MLLM.Workbench.Desktop.exe'
    if(-not(Test-Path -LiteralPath $desktopExe -PathType Leaf)){throw "Desktop executable missing after publish: $desktopExe"}

    Remove-Item -LiteralPath $zip,$shaFile -Force -ErrorAction SilentlyContinue
    $items=@(Get-ChildItem -LiteralPath $stage -Force | ForEach-Object {$_.FullName})
    if($items.Count -eq 0){throw 'Desktop package staging directory is empty'}
    Compress-Archive -Path $items -DestinationPath $zip -CompressionLevel Optimal -Force
    if(-not(Test-Path -LiteralPath $zip -PathType Leaf)){throw 'Desktop package ZIP was not created'}
    $sha=(Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant()
    [IO.File]::WriteAllText($shaFile,($sha+'  '+[IO.Path]::GetFileName($zip)+[Environment]::NewLine),[Text.Encoding]::ASCII)
    $size=(Get-Item -LiteralPath $zip).Length
    Write-Host "DESKTOP_PACKAGE=PASS zip=$zip bytes=$size sha256=$sha pre_materialized=PASS self_contained=PASS"
}finally{
    Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue
}
