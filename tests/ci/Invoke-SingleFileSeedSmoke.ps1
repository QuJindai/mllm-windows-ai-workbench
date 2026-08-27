[CmdletBinding()]
param([string]$SeedPath='.\dist\M_LLM_UNIVERSAL_INSTALLER_FULL.cmd')
$ErrorActionPreference='Stop'
Set-StrictMode -Version 2

$seed=(Resolve-Path $SeedPath -ErrorAction Stop).Path
[byte[]]$raw=[IO.File]::ReadAllBytes($seed)
if($null -ne ($raw | Where-Object {$_ -gt 127} | Select-Object -First 1)){throw 'Single-file seed CMD must be ASCII-only'}
$text=[IO.File]::ReadAllText($seed,[Text.Encoding]::ASCII)
if($text -notmatch '__MLLM_SEED_PAYLOAD__'){throw 'Seed payload marker missing'}

$isolated=Join-Path $env:RUNNER_TEMP ('M LLM seed path with spaces '+[guid]::NewGuid().ToString('N').Substring(0,8))
New-Item -ItemType Directory -Force -Path $isolated | Out-Null
$copy=Join-Path $isolated 'M_LLM_UNIVERSAL_INSTALLER_FULL.cmd'
Copy-Item -LiteralPath $seed -Destination $copy -Force
if(@(Get-ChildItem -LiteralPath $isolated -Force).Count -ne 1){throw 'Seed smoke directory must contain only the single CMD'}

$oldPath=$env:PATH
try{
    $env:PATH=$env:SystemRoot+'\System32;'+$env:SystemRoot+'\System32\WindowsPowerShell\v1.0'
    $out=@(& $copy '--seed-smoke' 2>&1)
    $rc=$LASTEXITCODE
}finally{$env:PATH=$oldPath}
$joined=($out -join "`n")
Write-Host $joined
if($rc -ne 0){throw "Single-file seed smoke failed rc=$rc"}
foreach($marker in @('UNIVERSAL_SEED_PAYLOAD=PASS','UNIVERSAL_SEED_FOUNDATION=PASS','UNIVERSAL_INSTALLER_PATHS=PASS','UNIVERSAL_SEED_SMOKE=PASS')){
    if($joined -notmatch [regex]::Escape($marker)){throw "Seed smoke marker missing: $marker"}
}
$m=[regex]::Match($joined,'UNIVERSAL_SEED_ROOT=([^\r\n]+)')
if(-not $m.Success){throw 'Seed extraction root marker missing'}
$root=$m.Groups[1].Value.Trim()
if(-not(Test-Path -LiteralPath $root -PathType Container)){throw "Seed extraction root missing: $root"}
$manifestPath=Join-Path $root 'config\source-manifest.json'
$foundation=Join-Path $root 'packages\workbench-foundation.zip'
foreach($path in @($manifestPath,$foundation,(Join-Path $root 'installer\Start-UniversalInstaller.ps1'))){
    if(-not(Test-Path -LiteralPath $path -PathType Leaf)){throw "Seed extracted file missing: $path"}
}
$manifest=Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
$pkg=@($manifest.packages | Where-Object {$_.role -eq 'workbench-foundation'}) | Select-Object -First 1
if($null -eq $pkg){throw 'Seed manifest lacks workbench-foundation package'}
$actual=(Get-FileHash -LiteralPath $foundation -Algorithm SHA256).Hash.ToLowerInvariant()
if($actual -ne ([string]$pkg.sha256).ToLowerInvariant()){throw 'Embedded foundation hash does not match runtime manifest'}
if([string]$pkg.sources[0].kind -ne 'local_file'){throw 'Embedded foundation first source must be local_file'}
Write-Host 'UNIVERSAL_SINGLE_FILE_SEED=PASS sibling_files=0 runtime_git_python_required=false'
