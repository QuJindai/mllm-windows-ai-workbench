[CmdletBinding()]
param(
    [string]$VersionId='c7-knowledge-microscope-20260830',
    [switch]$NoElevate,
    [switch]$NoLaunch
)

$ErrorActionPreference='Stop'
Set-StrictMode -Version 2

$bundleRoot=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$payload=Join-Path $bundleRoot 'payload\MLLM_WORKBENCH_C7_PORTABLE_win-x64.zip'
$payloadShaFile=$payload+'.sha256'
$manifest=Join-Path $bundleRoot 'config\source-manifest.json'
$universalEntry=Join-Path $PSScriptRoot 'Start-UniversalInstaller.ps1'

foreach($required in @($payload,$payloadShaFile,$manifest,$universalEntry)){
    if(-not(Test-Path -LiteralPath $required -PathType Leaf)){throw "C7 installer dependency missing: $required"}
}

function Test-C7Elevated {
    $identity=[Security.Principal.WindowsIdentity]::GetCurrent()
    $principal=New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Restart-C7Elevated {
    param([string]$RequestedVersion,[bool]$SkipLaunch)

    $payloadObject=[ordered]@{
        script=[IO.Path]::GetFullPath($PSCommandPath)
        version_id=$RequestedVersion
        no_launch=$SkipLaunch
    }
    $json=$payloadObject | ConvertTo-Json -Depth 4 -Compress
    $encodedPayload=[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($json))
    $bootstrap=@'
$payload='__PAYLOAD__'
$json=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($payload))
$o=$json | ConvertFrom-Json
$args=@('-NoElevate','-VersionId',[string]$o.version_id)
if([bool]$o.no_launch){$args+='-NoLaunch'}
& ([string]$o.script) @args
exit $LASTEXITCODE
'@
    $bootstrap=$bootstrap.Replace('__PAYLOAD__',$encodedPayload)
    $encodedCommand=[Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($bootstrap))
    $process=Start-Process -FilePath 'powershell.exe' -Verb RunAs -ArgumentList @(
        '-NoProfile','-ExecutionPolicy','Bypass','-EncodedCommand',$encodedCommand
    ) -Wait -PassThru
    exit $process.ExitCode
}

function Test-C7PayloadHash {
    $expected=((Get-Content -LiteralPath $payloadShaFile -Raw).Trim() -split '\s+')[0].ToLowerInvariant()
    if($expected -notmatch '^[0-9a-f]{64}$'){throw "C7 payload SHA sidecar is invalid: $payloadShaFile"}
    $actual=(Get-FileHash -LiteralPath $payload -Algorithm SHA256).Hash.ToLowerInvariant()
    if($actual -ne $expected){throw "C7 payload SHA mismatch expected=$expected actual=$actual"}
    return $actual
}

function New-C7Shortcut {
    param([string]$ShortcutPath,[string]$TargetPath,[string]$WorkingDirectory)
    $parent=Split-Path -Parent $ShortcutPath
    if(-not(Test-Path -LiteralPath $parent -PathType Container)){New-Item -ItemType Directory -Force -Path $parent | Out-Null}
    $shell=New-Object -ComObject WScript.Shell
    $shortcut=$shell.CreateShortcut($ShortcutPath)
    $shortcut.TargetPath=$TargetPath
    $shortcut.WorkingDirectory=$WorkingDirectory
    $shortcut.IconLocation=$TargetPath
    $shortcut.Description='M-LLM Workbench C7 - Knowledge Evidence Microscope'
    $shortcut.Save()
}

if((-not $NoElevate) -and (-not(Test-C7Elevated))){
    Restart-C7Elevated -RequestedVersion $VersionId -SkipLaunch ([bool]$NoLaunch)
}

$payloadSha=Test-C7PayloadHash

& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $universalEntry `
    -NoElevate `
    -VersionId $VersionId `
    -SourceManifestPath $manifest `
    -Action ImportOffline `
    -OfflinePackagePath $payload
$installRc=$LASTEXITCODE
if($installRc -ne 0){throw "Universal Installer failed for C7 payload rc=$installRc"}

if(-not $env:ProgramData){throw 'ProgramData environment variable is unavailable after installation'}
$pointerPath=Join-Path $env:ProgramData 'M-LLM\Workbench\current.json'
if(-not(Test-Path -LiteralPath $pointerPath -PathType Leaf)){throw "C7 active version pointer missing: $pointerPath"}
$pointer=Get-Content -LiteralPath $pointerPath -Raw -Encoding UTF8 | ConvertFrom-Json
if([string]$pointer.version_id -ne $VersionId){throw "C7 activation mismatch expected=$VersionId actual=$($pointer.version_id)"}
$installedRoot=[IO.Path]::GetFullPath([string]$pointer.version_path)
$installedExe=Join-Path $installedRoot 'desktop\MLLM.Workbench.Desktop.exe'
if(-not(Test-Path -LiteralPath $installedExe -PathType Leaf)){throw "C7 installed desktop executable missing: $installedExe"}

if(-not $NoLaunch){
    try{
        $desktop=[Environment]::GetFolderPath([Environment+SpecialFolder]::DesktopDirectory)
        if($desktop){New-C7Shortcut -ShortcutPath (Join-Path $desktop 'M-LLM Workbench C7.lnk') -TargetPath $installedExe -WorkingDirectory (Split-Path -Parent $installedExe)}
        $programs=[Environment]::GetFolderPath([Environment+SpecialFolder]::Programs)
        if($programs){New-C7Shortcut -ShortcutPath (Join-Path $programs 'M-LLM Workbench C7.lnk') -TargetPath $installedExe -WorkingDirectory (Split-Path -Parent $installedExe)}
    }catch{
        Write-Warning ('C7 installation succeeded but shortcut creation failed: '+$_.Exception.Message)
    }
    Start-Process -FilePath $installedExe -WorkingDirectory (Split-Path -Parent $installedExe) | Out-Null
}

Write-Host "C7_INSTALL=PASS version=$VersionId version_path=$installedRoot payload_sha256=$payloadSha activated=PASS desktop=$installedExe"
exit 0
