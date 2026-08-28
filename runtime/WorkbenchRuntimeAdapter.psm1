Set-StrictMode -Version 2
$ErrorActionPreference='Stop'

function Get-MLLMPropertyValue {
    param($Object,[Parameter(Mandatory=$true)][string]$Name,$Default=$null)
    if($null -eq $Object){return $Default}
    if($Object -is [Collections.IDictionary]){
        if($Object.Contains($Name)){return $Object[$Name]}
        return $Default
    }
    $property=$Object.PSObject.Properties[$Name]
    if($null -ne $property){return $property.Value}
    return $Default
}

function Read-MLLMJsonFile {
    param([Parameter(Mandatory=$true)][string]$Path)
    if(-not(Test-Path -LiteralPath $Path -PathType Leaf)){return $null}
    return (Get-Content -LiteralPath $Path -Raw -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop)
}

function Write-MLLMJsonAtomic {
    param([Parameter(Mandatory=$true)][string]$Path,[Parameter(Mandatory=$true)]$Value)
    $full=[IO.Path]::GetFullPath($Path)
    $parent=Split-Path -Parent $full
    if(-not(Test-Path -LiteralPath $parent -PathType Container)){New-Item -ItemType Directory -Force -Path $parent | Out-Null}
    $token=[guid]::NewGuid().ToString('N')
    $tmp=$full+'.tmp.'+$token
    $backup=$full+'.bak.'+$token
    $utf8=New-Object System.Text.UTF8Encoding -ArgumentList $false
    try{
        [IO.File]::WriteAllText($tmp,($Value | ConvertTo-Json -Depth 20),$utf8)
        if(Test-Path -LiteralPath $full -PathType Leaf){
            [IO.File]::Replace($tmp,$full,$backup)
            Remove-Item -LiteralPath $backup -Force -ErrorAction SilentlyContinue
        }else{
            [IO.File]::Move($tmp,$full)
        }
    }finally{
        Remove-Item -LiteralPath $tmp,$backup -Force -ErrorAction SilentlyContinue
    }
    return $full
}

function Get-MLLMModelCatalog {
    param([Parameter(Mandatory=$true)][string]$ProjectRoot)
    $manifestPath=Join-Path ([IO.Path]::GetFullPath($ProjectRoot)) 'config\models.json'
    $manifest=Read-MLLMJsonFile -Path $manifestPath
    if($null -eq $manifest -or $null -eq (Get-MLLMPropertyValue -Object $manifest -Name 'models' -Default $null)){throw ('MODEL_CATALOG_INVALID|'+$manifestPath)}
    return @($manifest.models)
}

function Get-MLLMManagedModelSidecars {
    param([Parameter(Mandatory=$true)][string]$DataRoot)
    $managedRoot=Join-Path ([IO.Path]::GetFullPath($DataRoot)) 'models\managed'
    if(-not(Test-Path -LiteralPath $managedRoot -PathType Container)){return @()}
    $rows=New-Object Collections.Generic.List[object]
    foreach($dir in @(Get-ChildItem -LiteralPath $managedRoot -Directory -ErrorAction SilentlyContinue)){
        $sidecarPath=Join-Path $dir.FullName 'model.mllm.json'
        if(-not(Test-Path -LiteralPath $sidecarPath -PathType Leaf)){continue}
        try{
            $sidecar=Read-MLLMJsonFile -Path $sidecarPath
            if($null -ne $sidecar){$rows.Add($sidecar)}
        }catch{}
    }
    return $rows.ToArray()
}

function Test-MLLMGgufMagic {
    param([Parameter(Mandatory=$true)][string]$Path)
    $stream=$null
    try{
        $stream=[IO.File]::Open($Path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
        if($stream.Length -lt 4){return $false}
        $buffer=New-Object byte[] 4
        $read=$stream.Read($buffer,0,4)
        if($read -ne 4){return $false}
        return ([Text.Encoding]::ASCII.GetString($buffer) -eq 'GGUF')
    }finally{
        if($null -ne $stream){$stream.Dispose()}
    }
}

function Get-MLLMFileSha256 {
    param([Parameter(Mandatory=$true)][string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant()
}

function Get-MLLMBuiltInModelPath {
    param($Definition,[Parameter(Mandatory=$true)][string]$DataRoot)
    $fileName=[string]$Definition.canonical_filename
    if(-not $fileName){throw ('MODEL_CATALOG_INVALID|canonical_filename missing for '+[string]$Definition.id)}
    if([string]$Definition.role -eq 'local-fast'){
        return Join-Path ([IO.Path]::GetFullPath($DataRoot)) ('models\Qwen3.5-4B\'+$fileName)
    }
    return Join-Path ([IO.Path]::GetFullPath($DataRoot)) ('models\'+[string]$Definition.id+'\'+$fileName)
}

function Get-MLLMManagedModelDefinition {
    param([Parameter(Mandatory=$true)][string]$DataRoot,[Parameter(Mandatory=$true)][string]$ModelId)
    foreach($sidecar in @(Get-MLLMManagedModelSidecars -DataRoot $DataRoot)){
        if([string](Get-MLLMPropertyValue -Object $sidecar -Name 'id' -Default '') -ne $ModelId){continue}
        $fileName=[string](Get-MLLMPropertyValue -Object $sidecar -Name 'file_name' -Default '')
        if(-not $fileName){continue}
        $modelRoot=Join-Path ([IO.Path]::GetFullPath($DataRoot)) ('models\managed\'+$ModelId)
        return [pscustomobject]@{
            id=$ModelId
            role=[string](Get-MLLMPropertyValue -Object $sidecar -Name 'role' -Default 'imported')
            display_name=[string](Get-MLLMPropertyValue -Object $sidecar -Name 'display_name' -Default $ModelId)
            canonical_filename=$fileName
            format='gguf'
            minimum_bytes=4
            sha256=$null
            source_kind='Imported'
            resolved_path=(Join-Path $modelRoot $fileName)
        }
    }
    return $null
}

function Resolve-MLLMModelDefinition {
    param(
        [Parameter(Mandatory=$true)][string]$ProjectRoot,
        [Parameter(Mandatory=$true)][string]$DataRoot,
        [Parameter(Mandatory=$true)][string]$ModelId
    )
    foreach($item in @(Get-MLLMModelCatalog -ProjectRoot $ProjectRoot)){
        if([string]$item.id -ne $ModelId){continue}
        return [pscustomobject]@{
            id=[string]$item.id
            role=[string]$item.role
            display_name=[string](Get-MLLMPropertyValue -Object $item -Name 'display_name' -Default ([string]$item.id))
            canonical_filename=[string]$item.canonical_filename
            format=[string](Get-MLLMPropertyValue -Object $item -Name 'format' -Default 'gguf')
            minimum_bytes=[long](Get-MLLMPropertyValue -Object $item -Name 'minimum_bytes' -Default 4)
            sha256=(Get-MLLMPropertyValue -Object $item -Name 'sha256' -Default $null)
            source_kind='BuiltIn'
            resolved_path=(Get-MLLMBuiltInModelPath -Definition $item -DataRoot $DataRoot)
        }
    }
    return (Get-MLLMManagedModelDefinition -DataRoot $DataRoot -ModelId $ModelId)
}

function Get-MLLMActiveModel {
    [CmdletBinding()]
    param([Parameter(Mandatory=$true)][ValidateNotNullOrEmpty()][string]$DataRoot)
    $path=Join-Path ([IO.Path]::GetFullPath($DataRoot)) 'state\active_model.json'
    if(-not(Test-Path -LiteralPath $path -PathType Leaf)){return $null}
    return (Read-MLLMJsonFile -Path $path)
}

function Test-MLLMWorkbenchModel {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)][ValidateNotNullOrEmpty()][string]$ProjectRoot,
        [Parameter(Mandatory=$true)][ValidateNotNullOrEmpty()][string]$DataRoot,
        [Parameter(Mandatory=$true)][ValidateNotNullOrEmpty()][string]$ModelId
    )

    $definition=Resolve-MLLMModelDefinition -ProjectRoot $ProjectRoot -DataRoot $DataRoot -ModelId $ModelId
    if($null -eq $definition){throw ('MODEL_NOT_FOUND|'+$ModelId)}

    $path=[IO.Path]::GetFullPath([string]$definition.resolved_path)
    $fileName=[IO.Path]::GetFileName($path)
    $minimum=[long]$definition.minimum_bytes
    $expected=$null
    if($null -ne $definition.sha256 -and -not [string]::IsNullOrWhiteSpace([string]$definition.sha256)){$expected=([string]$definition.sha256).ToLowerInvariant()}
    $integrity='Missing'
    $actual=$null
    $size=[long]0
    $errorCode=$null

    if(Test-Path -LiteralPath $path -PathType Leaf){
        $size=[long](Get-Item -LiteralPath $path -ErrorAction Stop).Length
        if(([string]$definition.format).ToLowerInvariant() -eq 'gguf' -and -not(Test-MLLMGgufMagic -Path $path)){
            $integrity='Failed'
            $errorCode='MODEL_FORMAT_INVALID'
        }elseif($size -lt $minimum){
            $integrity='Failed'
            $errorCode='MODEL_SIZE_INVALID'
        }else{
            $actual=Get-MLLMFileSha256 -Path $path
            if($null -eq $expected){
                $integrity='HashComputedUnanchored'
            }elseif($expected -notmatch '^[0-9a-f]{64}$'){
                $integrity='Failed'
                $errorCode='MODEL_HASH_CONTRACT_INVALID'
            }elseif($actual -eq $expected){
                $integrity='Sha256Pass'
            }else{
                $integrity='Failed'
                $errorCode='MODEL_HASH_MISMATCH'
            }
        }
    }

    $active=Get-MLLMActiveModel -DataRoot $DataRoot
    $activeId=$null
    if($null -ne $active){$activeId=[string](Get-MLLMPropertyValue -Object $active -Name 'modelId' -Default (Get-MLLMPropertyValue -Object $active -Name 'model_id' -Default (Get-MLLMPropertyValue -Object $active -Name 'id' -Default '')))}
    $quantization=$null
    if($fileName -match '(?i)(Q[0-9]+_[A-Z0-9_]+)'){$quantization=$Matches[1].ToUpperInvariant()}
    $blocked=$null
    if($integrity -eq 'Missing'){$blocked='MODEL_NOT_FOUND'}
    elseif($integrity -eq 'Failed'){$blocked=$errorCode}

    return [pscustomobject][ordered]@{
        id=[string]$definition.id
        role=[string]$definition.role
        displayName=[string]$definition.display_name
        sourceKind=[string]$definition.source_kind
        filePath=$path
        fileName=$fileName
        format=[string]$definition.format
        quantization=$quantization
        sizeBytes=$size
        minimumBytes=$minimum
        expectedSha256=$expected
        actualSha256=$actual
        integrityState=$integrity
        isActive=($activeId -eq [string]$definition.id)
        activationBlockedReason=$blocked
        errorCode=$errorCode
    }
}

function Get-MLLMModelInventory {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)][ValidateNotNullOrEmpty()][string]$ProjectRoot,
        [Parameter(Mandatory=$true)][ValidateNotNullOrEmpty()][string]$DataRoot
    )
    $ids=New-Object Collections.Generic.List[string]
    foreach($item in @(Get-MLLMModelCatalog -ProjectRoot $ProjectRoot)){
        $id=[string]$item.id
        if($id -and -not $ids.Contains($id)){$ids.Add($id)}
    }
    foreach($sidecar in @(Get-MLLMManagedModelSidecars -DataRoot $DataRoot)){
        $id=[string](Get-MLLMPropertyValue -Object $sidecar -Name 'id' -Default '')
        if($id -and -not $ids.Contains($id)){$ids.Add($id)}
    }
    $rows=New-Object Collections.Generic.List[object]
    foreach($id in $ids){$rows.Add((Test-MLLMWorkbenchModel -ProjectRoot $ProjectRoot -DataRoot $DataRoot -ModelId $id))}
    return $rows.ToArray()
}

function Import-MLLMManagedModel {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)][ValidateNotNullOrEmpty()][string]$ProjectRoot,
        [Parameter(Mandatory=$true)][ValidateNotNullOrEmpty()][string]$DataRoot,
        [Parameter(Mandatory=$true)][ValidateNotNullOrEmpty()][string]$SourcePath,
        [string]$DisplayName=''
    )

    $source=[IO.Path]::GetFullPath($SourcePath)
    if($source.StartsWith('\\',[StringComparison]::Ordinal)){throw 'MODEL_IMPORT_SOURCE_NOT_LOCAL|UNC paths are not accepted for managed model import'}
    if(-not(Test-Path -LiteralPath $source -PathType Leaf)){throw ('MODEL_NOT_FOUND|'+$source)}
    if([IO.Path]::GetExtension($source) -ne '.gguf'){throw 'MODEL_FORMAT_INVALID|Managed import accepts .gguf files only'}
    if(-not(Test-MLLMGgufMagic -Path $source)){throw 'MODEL_FORMAT_INVALID|GGUF magic is missing'}

    $dataFull=[IO.Path]::GetFullPath($DataRoot)
    $modelsRoot=Join-Path $dataFull 'models'
    $stagingRoot=Join-Path $modelsRoot '.staging'
    $managedRoot=Join-Path $modelsRoot 'managed'
    New-Item -ItemType Directory -Force -Path $stagingRoot,$managedRoot | Out-Null
    $stageDir=Join-Path $stagingRoot ([guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Force -Path $stageDir | Out-Null
    try{
        $staged=Join-Path $stageDir 'model.gguf'
        Copy-Item -LiteralPath $source -Destination $staged -Force -ErrorAction Stop
        if(-not(Test-MLLMGgufMagic -Path $staged)){throw 'MODEL_FORMAT_INVALID|Staged GGUF magic is invalid'}
        $sha=Get-MLLMFileSha256 -Path $staged
        $modelId='imported-'+$sha.Substring(0,12)
        $finalDir=Join-Path $managedRoot $modelId
        $finalName=[IO.Path]::GetFileName($source)
        if(-not $finalName.ToLowerInvariant().EndsWith('.gguf')){$finalName='model.gguf'}

        if(Test-Path -LiteralPath $finalDir -PathType Container){
            $existingSidecar=Read-MLLMJsonFile -Path (Join-Path $finalDir 'model.mllm.json')
            $existingHash=[string](Get-MLLMPropertyValue -Object $existingSidecar -Name 'actual_sha256' -Default '')
            $existingName=[string](Get-MLLMPropertyValue -Object $existingSidecar -Name 'file_name' -Default '')
            $existingFile=if($existingName){Join-Path $finalDir $existingName}else{$null}
            if($existingHash -eq $sha -and $existingFile -and (Test-Path -LiteralPath $existingFile -PathType Leaf) -and (Get-MLLMFileSha256 -Path $existingFile) -eq $sha){
                return (Test-MLLMWorkbenchModel -ProjectRoot $ProjectRoot -DataRoot $DataRoot -ModelId $modelId)
            }
            throw ('MODEL_ID_COLLISION|'+$modelId)
        }

        $renamed=Join-Path $stageDir $finalName
        Move-Item -LiteralPath $staged -Destination $renamed -Force -ErrorAction Stop
        if(-not $DisplayName){$DisplayName=[IO.Path]::GetFileNameWithoutExtension($finalName)}
        $sidecar=[ordered]@{
            schema='mllm.model.v1'
            id=$modelId
            role='imported'
            display_name=$DisplayName
            file_name=$finalName
            actual_sha256=$sha
            imported_at=(Get-Date).ToString('o')
        }
        $sidecar | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $stageDir 'model.mllm.json') -Encoding UTF8
        Move-Item -LiteralPath $stageDir -Destination $finalDir -ErrorAction Stop
        return (Test-MLLMWorkbenchModel -ProjectRoot $ProjectRoot -DataRoot $DataRoot -ModelId $modelId)
    }finally{
        if(Test-Path -LiteralPath $stageDir -PathType Container){Remove-Item -LiteralPath $stageDir -Recurse -Force -ErrorAction SilentlyContinue}
    }
}

function Import-MLLMRuntimeOwnershipProvider {
    param([Parameter(Mandatory=$true)][string]$ProjectRoot)
    if($null -ne (Get-Command Test-MLLMRecordedProcess -ErrorAction SilentlyContinue)){return}
    $runtimeModule=Join-Path ([IO.Path]::GetFullPath($ProjectRoot)) 'engine\Runtime.psm1'
    if(Test-Path -LiteralPath $runtimeModule -PathType Leaf){Import-Module $runtimeModule -Force -ErrorAction Stop}
}

function Test-MLLMLocalModelServiceRunning {
    param([Parameter(Mandatory=$true)][string]$ProjectRoot,[Parameter(Mandatory=$true)][string]$DataRoot)
    $statePath=Join-Path ([IO.Path]::GetFullPath($DataRoot)) 'state\services\local-model-api.json'
    if(-not(Test-Path -LiteralPath $statePath -PathType Leaf)){return $false}
    $record=Read-MLLMJsonFile -Path $statePath
    $recordedState=[string](Get-MLLMPropertyValue -Object $record -Name 'state' -Default '')
    $recordedPid=[int](Get-MLLMPropertyValue -Object $record -Name 'pid' -Default 0)
    if($recordedPid -le 0 -or $recordedState -notin @('Running','Starting','Degraded')){return $false}
    Import-MLLMRuntimeOwnershipProvider -ProjectRoot $ProjectRoot
    $checker=Get-Command Test-MLLMRecordedProcess -ErrorAction SilentlyContinue
    if($null -eq $checker){throw 'MODEL_SERVICE_OWNERSHIP_UNAVAILABLE|Cannot safely determine local model service ownership'}
    return [bool](Test-MLLMRecordedProcess -ProcessId $recordedPid)
}

function Set-MLLMActiveModel {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)][ValidateNotNullOrEmpty()][string]$ProjectRoot,
        [Parameter(Mandatory=$true)][ValidateNotNullOrEmpty()][string]$DataRoot,
        [Parameter(Mandatory=$true)][ValidateNotNullOrEmpty()][string]$ModelId
    )

    $candidate=Test-MLLMWorkbenchModel -ProjectRoot $ProjectRoot -DataRoot $DataRoot -ModelId $ModelId
    if([string]$candidate.integrityState -eq 'Missing'){throw ('MODEL_NOT_FOUND|'+$ModelId)}
    if([string]$candidate.integrityState -eq 'Failed'){
        $code=[string]$candidate.errorCode
        if(-not $code){$code='MODEL_FORMAT_INVALID'}
        throw ($code+'|'+$ModelId)
    }
    if(Test-MLLMLocalModelServiceRunning -ProjectRoot $ProjectRoot -DataRoot $DataRoot){throw 'MODEL_ACTIVE_SERVICE_RUNNING|Stop local-model-api before switching the active model'}

    $previous=Get-MLLMActiveModel -DataRoot $DataRoot
    $previousId=$null
    if($null -ne $previous){$previousId=[string](Get-MLLMPropertyValue -Object $previous -Name 'modelId' -Default '')}
    $pointer=[ordered]@{
        schema='mllm.active-model.v1'
        modelId=$ModelId
        modelPath=[string]$candidate.filePath
        actualSha256=[string]$candidate.actualSha256
        previousModelId=if($previousId){$previousId}else{$null}
        activatedAt=(Get-Date).ToString('o')
    }
    $path=Join-Path ([IO.Path]::GetFullPath($DataRoot)) 'state\active_model.json'
    Write-MLLMJsonAtomic -Path $path -Value $pointer | Out-Null
    return (Get-MLLMActiveModel -DataRoot $DataRoot)
}

Export-ModuleMember -Function Get-MLLMModelInventory,Test-MLLMWorkbenchModel,Get-MLLMActiveModel,Import-MLLMManagedModel,Set-MLLMActiveModel
