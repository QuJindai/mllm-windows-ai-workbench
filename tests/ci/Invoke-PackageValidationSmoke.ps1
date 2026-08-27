[CmdletBinding()]
param()
$ErrorActionPreference='Stop'
Set-StrictMode -Version 2

$Root=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$module=Join-Path $Root 'installer\PackageValidation.psm1'
if(-not(Test-Path -LiteralPath $module -PathType Leaf)){throw "PackageValidation.psm1 missing: $module"}
Import-Module $module -Force -ErrorAction Stop
Add-Type -AssemblyName System.IO.Compression -ErrorAction Stop
Add-Type -AssemblyName System.IO.Compression.FileSystem -ErrorAction Stop

$temp=Join-Path $env:RUNNER_TEMP ('mllm-pkg-'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $temp | Out-Null
$stageSrc=Join-Path $temp 'stage-src'
New-Item -ItemType Directory -Force -Path $stageSrc | Out-Null

$files=[ordered]@{
    'Start_M_LLM_Workbench.ps1'="[CmdletBinding()]`r`nparam()`r`nWrite-Host 'START_OK'`r`n"
    'Bootstrap_SafeCore.ps1'="[CmdletBinding()]`r`nparam([string]`$ProjectRoot='')`r`nWrite-Host 'BOOTSTRAP_OK'`r`n"
    'M_LLM_PHYSICAL_PREFLIGHT.ps1'="[CmdletBinding()]`r`nparam()`r`nWrite-Host 'PHYSICAL_OK'`r`n"
    'M_LLM_GUI_PREFLIGHT.ps1'="[CmdletBinding()]`r`nparam()`r`nWrite-Host 'GUI_OK'`r`n"
}
foreach($name in $files.Keys){[IO.File]::WriteAllText((Join-Path $stageSrc $name),$files[$name],(New-Object Text.UTF8Encoding($false)))}

$validZip=Join-Path $temp 'valid.zip'
[IO.Compression.ZipFile]::CreateFromDirectory($stageSrc,$validZip)
$validSha=(Get-FileHash -LiteralPath $validZip -Algorithm SHA256).Hash.ToLowerInvariant()
if(-not(Test-MLLMPackageHash -Path $validZip -ExpectedSha256 $validSha)){throw 'correct package hash was rejected'}
if(Test-MLLMPackageHash -Path $validZip -ExpectedSha256 ('0'*64)){throw 'wrong package hash was accepted'}

$extract=Join-Path $temp 'extract-valid'
$r=Expand-MLLMSafeArchive -ArchivePath $validZip -Destination $extract
if([string]$r.status -ne 'PASS'){throw "valid ZIP extraction failed: $($r.status)"}
$contract=Test-MLLMStageContract -StageRoot $extract
if([string]$contract.status -ne 'PASS'){throw "valid stage contract failed: $(@($contract.errors) -join ' | ')"}
Write-Host 'PACKAGE_VALIDATION_SMOKE=PASS'
Write-Host 'STAGE_CONTRACT_SMOKE=PASS'

$missing=Join-Path $temp 'missing-stage'
New-Item -ItemType Directory -Force -Path $missing | Out-Null
Copy-Item -LiteralPath (Join-Path $stageSrc 'Bootstrap_SafeCore.ps1') -Destination $missing
$missingContract=Test-MLLMStageContract -StageRoot $missing
if([string]$missingContract.status -ne 'FAIL'){throw 'stage missing required files was accepted'}

$evilZip=Join-Path $temp 'evil.zip'
$fs=[IO.File]::Open($evilZip,[IO.FileMode]::CreateNew,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
$archive=New-Object IO.Compression.ZipArchive($fs,[IO.Compression.ZipArchiveMode]::Create,$false)
try{
    $entry=$archive.CreateEntry('..\escape.txt')
    $stream=$entry.Open()
    try{
        [byte[]]$bytes=[Text.Encoding]::UTF8.GetBytes('escape')
        $stream.Write($bytes,0,$bytes.Length)
    }finally{$stream.Dispose()}
}finally{$archive.Dispose();$fs.Dispose()}
$evilDest=Join-Path $temp 'evil-dest'
$rejected=$false
try{Expand-MLLMSafeArchive -ArchivePath $evilZip -Destination $evilDest | Out-Null}catch{$rejected=$true}
if(-not $rejected){throw 'ZIP traversal payload was not rejected'}
if(Test-Path -LiteralPath (Join-Path $temp 'escape.txt') -PathType Leaf){throw 'ZIP traversal escaped destination'}
Write-Host 'ZIP_TRAVERSAL_REJECTION=PASS'
