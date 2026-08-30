[CmdletBinding()]
param(
    [string]$OutputRoot='',
    [string]$SourceSha='',
    [string]$VersionId='c7-knowledge-microscope-20260830'
)

$ErrorActionPreference='Stop'
Set-StrictMode -Version 2
$root=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if(-not $OutputRoot){$OutputRoot=Join-Path $root 'artifacts\c7-release'}
$OutputRoot=[IO.Path]::GetFullPath($OutputRoot)
if(-not(Test-Path -LiteralPath $OutputRoot -PathType Container)){New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null}

if(-not $SourceSha){$SourceSha=[string]$env:GITHUB_SHA}
if(-not $SourceSha){
    try{
        $candidate=(& git -C $root rev-parse HEAD 2>$null | Select-Object -First 1)
        if($candidate){$SourceSha=[string]$candidate}
    }catch{}
}
if(-not $SourceSha){$SourceSha='unknown'}
$SourceSha=$SourceSha.Trim()

$portableName='MLLM_WORKBENCH_C7_PORTABLE_win-x64.zip'
$installerName='MLLM_WORKBENCH_C7_OFFLINE_INSTALLER_win-x64.zip'
$portable=Join-Path $OutputRoot $portableName
$portableShaFile=$portable+'.sha256'
$installerZip=Join-Path $OutputRoot $installerName
$installerShaFile=$installerZip+'.sha256'
$tempBuild=Join-Path $env:TEMP ('mllm-c7-portable-'+[guid]::NewGuid().ToString('N'))
$stage=Join-Path $env:TEMP ('mllm-c7-installer-'+[guid]::NewGuid().ToString('N'))

function Write-ShaSidecar {
    param([Parameter(Mandatory=$true)][string]$Path)
    $sha=(Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    $sidecar=$Path+'.sha256'
    [IO.File]::WriteAllText($sidecar,($sha+'  '+[IO.Path]::GetFileName($Path)+[Environment]::NewLine),[Text.Encoding]::ASCII)
    return $sha
}

function Copy-DirectoryExact {
    param([Parameter(Mandatory=$true)][string]$Source,[Parameter(Mandatory=$true)][string]$Destination)
    if(-not(Test-Path -LiteralPath $Source -PathType Container)){throw "Required release source directory missing: $Source"}
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    foreach($item in Get-ChildItem -LiteralPath $Source -Force){
        Copy-Item -LiteralPath $item.FullName -Destination $Destination -Recurse -Force
    }
}

try{
    New-Item -ItemType Directory -Force -Path $tempBuild,$stage | Out-Null

    $portableBuilder=Join-Path $root 'ci\package_desktop_phase_a.ps1'
    if(-not(Test-Path -LiteralPath $portableBuilder -PathType Leaf)){throw "Portable desktop packager missing: $portableBuilder"}
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $portableBuilder -OutputRoot $tempBuild -Configuration Release
    if($LASTEXITCODE -ne 0){throw "Portable desktop packaging failed rc=$LASTEXITCODE"}

    $builtPortable=Join-Path $tempBuild 'MLLM_WORKBENCH_DESKTOP_PHASE_A_win-x64.zip'
    if(-not(Test-Path -LiteralPath $builtPortable -PathType Leaf)){throw "Portable payload was not produced: $builtPortable"}
    Remove-Item -LiteralPath $portable,$portableShaFile,$installerZip,$installerShaFile -Force -ErrorAction SilentlyContinue
    Copy-Item -LiteralPath $builtPortable -Destination $portable -Force
    $portableSha=Write-ShaSidecar -Path $portable

    $releaseCmd=Join-Path $root 'release\INSTALL_M_LLM_C7.cmd'
    if(-not(Test-Path -LiteralPath $releaseCmd -PathType Leaf)){throw "C7 one-click installer entry missing: $releaseCmd"}
    Copy-Item -LiteralPath $releaseCmd -Destination (Join-Path $stage 'INSTALL_M_LLM_C7.cmd') -Force

    Copy-DirectoryExact -Source (Join-Path $root 'installer') -Destination (Join-Path $stage 'installer')

    $stageConfig=Join-Path $stage 'config'
    New-Item -ItemType Directory -Force -Path $stageConfig | Out-Null
    $sourceManifest=Join-Path $root 'config\source-manifest.json'
    if(-not(Test-Path -LiteralPath $sourceManifest -PathType Leaf)){throw "C7 source manifest missing: $sourceManifest"}
    Copy-Item -LiteralPath $sourceManifest -Destination (Join-Path $stageConfig 'source-manifest.json') -Force

    $stagePayload=Join-Path $stage 'payload'
    New-Item -ItemType Directory -Force -Path $stagePayload | Out-Null
    Copy-Item -LiteralPath $portable -Destination (Join-Path $stagePayload $portableName) -Force
    Copy-Item -LiteralPath $portableShaFile -Destination (Join-Path $stagePayload ($portableName+'.sha256')) -Force

    $buildUtc=[DateTimeOffset]::UtcNow.ToString('O')
    $releaseInfo=@"
M-LLM Workbench C7 Offline Release
VersionId=$VersionId
SourceCommit=$SourceSha
FunctionalBaseline=b25c65e9b9c273d97722fbd43f736e42422bcdc5
BuildUtc=$buildUtc
Platform=Windows x64
DesktopPublish=self-contained .NET 8 win-x64
PortableFile=$portableName
PortableSha256=$portableSha
InstallerEngine=Universal Installer / ImportOffline
InstallVerification=SHA256 + safe extraction + stage contract + version activation + installed desktop smoke
Usage=Extract this ZIP, then double-click INSTALL_M_LLM_C7.cmd
"@
    [IO.File]::WriteAllText((Join-Path $stage 'RELEASE_INFO.txt'),$releaseInfo,(New-Object Text.UTF8Encoding($false)))

    $items=@(Get-ChildItem -LiteralPath $stage -Force | ForEach-Object {$_.FullName})
    if($items.Count -eq 0){throw 'C7 installer staging directory is empty'}
    Compress-Archive -Path $items -DestinationPath $installerZip -CompressionLevel Optimal -Force
    if(-not(Test-Path -LiteralPath $installerZip -PathType Leaf)){throw "C7 offline installer ZIP was not created: $installerZip"}
    $installerSha=Write-ShaSidecar -Path $installerZip

    $portableBytes=(Get-Item -LiteralPath $portable).Length
    $installerBytes=(Get-Item -LiteralPath $installerZip).Length
    Write-Host "C7_RELEASE_PACKAGE=PASS version=$VersionId source_sha=$SourceSha portable=$portable portable_bytes=$portableBytes portable_sha256=$portableSha installer=$installerZip installer_bytes=$installerBytes installer_sha256=$installerSha"
}finally{
    Remove-Item -LiteralPath $tempBuild -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue
}
