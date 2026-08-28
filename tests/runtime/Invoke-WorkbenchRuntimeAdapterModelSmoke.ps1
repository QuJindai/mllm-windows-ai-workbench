[CmdletBinding()]
param()

$ErrorActionPreference='Stop'
Set-StrictMode -Version 2
$root=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$module=Join-Path $root 'runtime\WorkbenchRuntimeAdapter.psm1'
if(-not(Test-Path -LiteralPath $module -PathType Leaf)){throw "WorkbenchRuntimeAdapter.psm1 missing: $module"}
Import-Module $module -Force -ErrorAction Stop

foreach($commandName in @('Get-MLLMModelInventory','Test-MLLMWorkbenchModel','Get-MLLMActiveModel')){
    if($null -eq (Get-Command $commandName -ErrorAction SilentlyContinue)){throw "Runtime adapter command missing: $commandName"}
}

$production=(Get-Content -LiteralPath (Join-Path $root 'config\models.json') -Raw | ConvertFrom-Json).models | Where-Object {$_.id -eq 'qwen35-4b-q4km'} | Select-Object -First 1
if($null -eq $production){throw 'Production qwen35-4b-q4km definition missing'}
if($null -ne $production.sha256){throw 'Production model unexpectedly gained a trusted SHA256; update this contract deliberately'}

$testRoot=Join-Path $env:RUNNER_TEMP ('mllm phase b model adapter '+[guid]::NewGuid().ToString('N'))
$project=Join-Path $testRoot 'project'
$data=Join-Path $testRoot 'data'
$configDir=Join-Path $project 'config'
$modelDir=Join-Path $data 'models\Qwen3.5-4B'
New-Item -ItemType Directory -Force -Path $configDir,$modelDir | Out-Null

function Set-TestManifest {
    param([string]$FileName='fixture.gguf',[long]$MinimumBytes=4,[AllowNull()][string]$ExpectedSha256=$null)
    $manifest=[ordered]@{
        models=@([ordered]@{
            id='fixture-built-in'
            role='local-fast'
            repository='fixture/local'
            allow_patterns=@('*.gguf')
            canonical_filename=$FileName
            filename_candidates=@($FileName)
            format='gguf'
            minimum_bytes=$MinimumBytes
            sha256=$ExpectedSha256
        })
    }
    $manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $configDir 'models.json') -Encoding UTF8
}

function Write-Bytes {
    param([string]$Path,[byte[]]$Bytes)
    [IO.File]::WriteAllBytes($Path,$Bytes)
}

try{
    $file=Join-Path $modelDir 'fixture.gguf'

    Set-TestManifest
    $missing=Test-MLLMWorkbenchModel -ProjectRoot $project -DataRoot $data -ModelId 'fixture-built-in'
    if([string]$missing.integrityState -ne 'Missing'){throw "Missing model state mismatch: $($missing.integrityState)"}

    Write-Bytes -Path $file -Bytes ([Text.Encoding]::ASCII.GetBytes('NOPEfixture'))
    $badMagic=Test-MLLMWorkbenchModel -ProjectRoot $project -DataRoot $data -ModelId 'fixture-built-in'
    if([string]$badMagic.integrityState -ne 'Failed' -or [string]$badMagic.errorCode -ne 'MODEL_FORMAT_INVALID'){
        throw "Bad GGUF magic did not fail closed: state=$($badMagic.integrityState) code=$($badMagic.errorCode)"
    }

    Write-Bytes -Path $file -Bytes ([Text.Encoding]::ASCII.GetBytes('GGUFok'))
    Set-TestManifest -MinimumBytes 64
    $tooSmall=Test-MLLMWorkbenchModel -ProjectRoot $project -DataRoot $data -ModelId 'fixture-built-in'
    if([string]$tooSmall.integrityState -ne 'Failed' -or [string]$tooSmall.errorCode -ne 'MODEL_SIZE_INVALID'){
        throw "Minimum-size contract did not fail closed: state=$($tooSmall.integrityState) code=$($tooSmall.errorCode)"
    }

    Set-TestManifest -MinimumBytes 4 -ExpectedSha256 $null
    $unanchored=Test-MLLMWorkbenchModel -ProjectRoot $project -DataRoot $data -ModelId 'fixture-built-in'
    if([string]$unanchored.integrityState -ne 'HashComputedUnanchored'){throw "Null expected SHA incorrectly treated as trusted: $($unanchored.integrityState)"}
    if(([string]$unanchored.actualSha256) -notmatch '^[0-9a-f]{64}$'){throw 'Actual SHA256 was not computed for structurally valid model'}
    if($null -ne $unanchored.expectedSha256 -and [string]$unanchored.expectedSha256){throw 'Expected SHA256 should remain null for unanchored model'}

    $actual=(Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant()
    Set-TestManifest -MinimumBytes 4 -ExpectedSha256 $actual
    $anchored=Test-MLLMWorkbenchModel -ProjectRoot $project -DataRoot $data -ModelId 'fixture-built-in'
    if([string]$anchored.integrityState -ne 'Sha256Pass'){throw "Trusted SHA match did not pass: $($anchored.integrityState)"}

    Set-TestManifest -MinimumBytes 4 -ExpectedSha256 ('0'*64)
    $mismatch=Test-MLLMWorkbenchModel -ProjectRoot $project -DataRoot $data -ModelId 'fixture-built-in'
    if([string]$mismatch.integrityState -ne 'Failed' -or [string]$mismatch.errorCode -ne 'MODEL_HASH_MISMATCH'){
        throw "Trusted SHA mismatch did not fail closed: state=$($mismatch.integrityState) code=$($mismatch.errorCode)"
    }

    Set-TestManifest -MinimumBytes 4 -ExpectedSha256 $null
    $inventory=@(Get-MLLMModelInventory -ProjectRoot $project -DataRoot $data)
    if($inventory.Count -ne 1){throw "Expected one inventory row, got $($inventory.Count)"}
    if([string]$inventory[0].integrityState -ne 'HashComputedUnanchored'){throw "Inventory integrity mismatch: $($inventory[0].integrityState)"}
    if([string]$inventory[0].sourceKind -ne 'BuiltIn'){throw "Inventory source kind mismatch: $($inventory[0].sourceKind)"}

    $active=Get-MLLMActiveModel -DataRoot $data
    if($null -ne $active){throw 'Fresh DataRoot unexpectedly has an active model pointer'}

    Write-Host 'PHASE_B_MODEL_ADAPTER=PASS missing=PASS magic=PASS size=PASS unanchored=PASS sha_match=PASS sha_mismatch=PASS inventory=PASS active_empty=PASS'
}finally{
    Remove-Item -LiteralPath $testRoot -Recurse -Force -ErrorAction SilentlyContinue
}
