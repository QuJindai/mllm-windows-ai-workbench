[CmdletBinding()]
param()

$ErrorActionPreference='Stop'
Set-StrictMode -Version 2
$root=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$module=Join-Path $root 'runtime\WorkbenchRuntimeAdapter.psm1'
if(-not(Test-Path -LiteralPath $module -PathType Leaf)){throw "WorkbenchRuntimeAdapter.psm1 missing: $module"}
Import-Module $module -Force -ErrorAction Stop

foreach($commandName in @('Get-MLLMModelInventory','Test-MLLMWorkbenchModel','Get-MLLMActiveModel','Import-MLLMManagedModel','Set-MLLMActiveModel')){
    if($null -eq (Get-Command $commandName -ErrorAction SilentlyContinue)){throw "Runtime adapter command missing: $commandName"}
}

$production=(Get-Content -LiteralPath (Join-Path $root 'config\models.json') -Raw | ConvertFrom-Json).models | Where-Object {$_.id -eq 'qwen35-4b-q4km'} | Select-Object -First 1
if($null -eq $production){throw 'Production qwen35-4b-q4km definition missing'}
if($null -ne $production.sha256){throw 'Production model unexpectedly gained a trusted SHA256; update this contract deliberately'}

$testRoot=Join-Path $env:RUNNER_TEMP ('mllm phase b model adapter '+[guid]::NewGuid().ToString('N'))
$project=Join-Path $testRoot 'project'
$data=Join-Path $testRoot 'data'
$configDir=Join-Path $project 'config'
$engineDir=Join-Path $project 'engine'
$modelDir=Join-Path $data 'models\Qwen3.5-4B'
New-Item -ItemType Directory -Force -Path $configDir,$engineDir,$modelDir | Out-Null

@'
function Test-MLLMRecordedProcess {
    param([int]$ProcessId)
    return ($ProcessId -eq $PID)
}
Export-ModuleMember -Function Test-MLLMRecordedProcess
'@ | Set-Content -LiteralPath (Join-Path $engineDir 'Runtime.psm1') -Encoding ASCII

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
    $parent=Split-Path -Parent $Path
    if(-not(Test-Path -LiteralPath $parent -PathType Container)){New-Item -ItemType Directory -Force -Path $parent | Out-Null}
    [IO.File]::WriteAllBytes($Path,$Bytes)
}

function Assert-ThrowsCode {
    param([scriptblock]$Action,[string]$Code)
    $threw=$false
    try{& $Action}catch{
        $threw=$true
        if($_.Exception.Message -notmatch [regex]::Escape($Code)){throw "Expected error code $Code, got: $($_.Exception.Message)"}
    }
    if(-not $threw){throw "Expected operation to throw $Code"}
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

    $sourceDir=Join-Path $testRoot 'source models'
    New-Item -ItemType Directory -Force -Path $sourceDir | Out-Null
    $source=Join-Path $sourceDir 'managed model.gguf'
    Write-Bytes -Path $source -Bytes ([Text.Encoding]::ASCII.GetBytes('GGUFmanaged-content-v1'))
    $sourceSha=(Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant()
    $expectedId='imported-'+$sourceSha.Substring(0,12)

    $imported=Import-MLLMManagedModel -ProjectRoot $project -DataRoot $data -SourcePath $source -DisplayName 'Managed Fixture'
    if([string]$imported.id -ne $expectedId){throw "Imported model id mismatch: $($imported.id)"}
    if([string]$imported.sourceKind -ne 'Imported'){throw "Imported source kind mismatch: $($imported.sourceKind)"}
    if([string]$imported.actualSha256 -ne $sourceSha){throw 'Imported model SHA mismatch'}
    if(-not(Test-Path -LiteralPath ([string]$imported.filePath) -PathType Leaf)){throw 'Imported managed GGUF missing'}
    $sidecar=Join-Path (Split-Path -Parent ([string]$imported.filePath)) 'model.mllm.json'
    if(-not(Test-Path -LiteralPath $sidecar -PathType Leaf)){throw 'Managed model sidecar missing'}
    if($null -ne (Get-MLLMActiveModel -DataRoot $data)){throw 'Import must never auto-activate a model'}

    $same=Import-MLLMManagedModel -ProjectRoot $project -DataRoot $data -SourcePath $source -DisplayName 'Managed Fixture'
    if([string]$same.id -ne $expectedId -or [string]$same.actualSha256 -ne $sourceSha){throw 'Same-content import was not idempotent'}

    $activated=Set-MLLMActiveModel -ProjectRoot $project -DataRoot $data -ModelId $expectedId
    if([string]$activated.modelId -ne $expectedId){throw "Active pointer did not switch to imported model: $($activated.modelId)"}
    $pointerBefore=(Get-Content -LiteralPath (Join-Path $data 'state\active_model.json') -Raw)

    $badImport=Join-Path $sourceDir 'bad.gguf'
    Write-Bytes -Path $badImport -Bytes ([Text.Encoding]::ASCII.GetBytes('NOPEbad-import'))
    Assert-ThrowsCode -Code 'MODEL_FORMAT_INVALID' -Action { Import-MLLMManagedModel -ProjectRoot $project -DataRoot $data -SourcePath $badImport | Out-Null }
    if((Get-Content -LiteralPath (Join-Path $data 'state\active_model.json') -Raw) -ne $pointerBefore){throw 'Failed import changed active model pointer'}

    $collisionSource=Join-Path $sourceDir 'collision.gguf'
    Write-Bytes -Path $collisionSource -Bytes ([Text.Encoding]::ASCII.GetBytes('GGUFcollision-source'))
    $collisionSha=(Get-FileHash -LiteralPath $collisionSource -Algorithm SHA256).Hash.ToLowerInvariant()
    $collisionId='imported-'+$collisionSha.Substring(0,12)
    $collisionDir=Join-Path $data ('models\managed\'+$collisionId)
    New-Item -ItemType Directory -Force -Path $collisionDir | Out-Null
    [ordered]@{schema='mllm.model.v1';id=$collisionId;role='imported';display_name='collision';file_name='existing.gguf';actual_sha256=('f'*64);imported_at=(Get-Date).ToString('o')} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $collisionDir 'model.mllm.json') -Encoding UTF8
    Write-Bytes -Path (Join-Path $collisionDir 'existing.gguf') -Bytes ([Text.Encoding]::ASCII.GetBytes('GGUFexisting'))
    Assert-ThrowsCode -Code 'MODEL_ID_COLLISION' -Action { Import-MLLMManagedModel -ProjectRoot $project -DataRoot $data -SourcePath $collisionSource | Out-Null }
    if((Get-Content -LiteralPath (Join-Path $collisionDir 'model.mllm.json') -Raw) -notmatch ('f'*64)){throw 'Collision import overwrote existing model'}

    $invalidId='manual-invalid'
    $invalidDir=Join-Path $data ('models\managed\'+$invalidId)
    New-Item -ItemType Directory -Force -Path $invalidDir | Out-Null
    Write-Bytes -Path (Join-Path $invalidDir 'invalid.gguf') -Bytes ([Text.Encoding]::ASCII.GetBytes('NOPEinvalid'))
    [ordered]@{schema='mllm.model.v1';id=$invalidId;role='imported';display_name='invalid';file_name='invalid.gguf';actual_sha256=('1'*64);imported_at=(Get-Date).ToString('o')} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $invalidDir 'model.mllm.json') -Encoding UTF8
    Assert-ThrowsCode -Code 'MODEL_FORMAT_INVALID' -Action { Set-MLLMActiveModel -ProjectRoot $project -DataRoot $data -ModelId $invalidId | Out-Null }
    if([string](Get-MLLMActiveModel -DataRoot $data).modelId -ne $expectedId){throw 'Failed activation changed previous active pointer'}

    $serviceStateDir=Join-Path $data 'state\services'
    New-Item -ItemType Directory -Force -Path $serviceStateDir | Out-Null
    [ordered]@{serviceId='local-model-api';pid=$PID;state='Running'} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $serviceStateDir 'local-model-api.json') -Encoding UTF8
    Assert-ThrowsCode -Code 'MODEL_ACTIVE_SERVICE_RUNNING' -Action { Set-MLLMActiveModel -ProjectRoot $project -DataRoot $data -ModelId 'fixture-built-in' | Out-Null }
    if([string](Get-MLLMActiveModel -DataRoot $data).modelId -ne $expectedId){throw 'Running-service activation guard changed active pointer'}

    Write-Host 'PHASE_B_MODEL_ADAPTER=PASS missing=PASS magic=PASS size=PASS unanchored=PASS sha_match=PASS sha_mismatch=PASS inventory=PASS import=PASS idempotent=PASS collision=PASS activate=PASS preserve=PASS running_guard=PASS'
}finally{
    Remove-Item -LiteralPath $testRoot -Recurse -Force -ErrorAction SilentlyContinue
}
