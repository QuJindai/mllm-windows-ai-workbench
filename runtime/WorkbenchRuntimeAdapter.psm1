Set-StrictMode -Version 2
$ErrorActionPreference='Stop'

function Read-MLLMJsonFile {
    param([Parameter(Mandatory=$true)][string]$Path)
    if(-not(Test-Path -LiteralPath $Path -PathType Leaf)){return $null}
    return (Get-Content -LiteralPath $Path -Raw -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop)
}

function Get-MLLMModelCatalog {
    param([Parameter(Mandatory=$true)][string]$ProjectRoot)
    $manifestPath=Join-Path ([IO.Path]::GetFullPath($ProjectRoot)) 'config\models.json'
    $manifest=Read-MLLMJsonFile -Path $manifestPath
    if($null -eq $manifest -or $null -eq $manifest.models){throw ('MODEL_CATALOG_INVALID|'+$manifestPath)}
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
        if([string]$sidecar.id -ne $ModelId){continue}
        $fileName=[string]$sidecar.file_name
        $modelRoot=Join-Path ([IO.Path]::GetFullPath($DataRoot)) ('models\managed\'+$ModelId)
        return [pscustomobject]@{
            id=$ModelId
            role=if($sidecar.role){[string]$sidecar.role}else{'imported'}
            display_name=if($sidecar.display_name){[string]$sidecar.display_name}else{$ModelId}
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
            display_name=if($item.PSObject.Properties['display_name'] -and [string]$item.display_name){[string]$item.display_name}else{[string]$item.id}
            canonical_filename=[string]$item.canonical_filename
            format=if([string]$item.format){[string]$item.format}else{'gguf'}
            minimum_bytes=[long]$item.minimum_bytes
            sha256=if($item.PSObject.Properties['sha256']){$item.sha256}else{$null}
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
    if($null -ne $active){
        if($active.PSObject.Properties['modelId']){$activeId=[string]$active.modelId}
        elseif($active.PSObject.Properties['model_id']){$activeId=[string]$active.model_id}
        elseif($active.PSObject.Properties['id']){$activeId=[string]$active.id}
    }
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
        $id=[string]$sidecar.id
        if($id -and -not $ids.Contains($id)){$ids.Add($id)}
    }
    $rows=New-Object Collections.Generic.List[object]
    foreach($id in $ids){$rows.Add((Test-MLLMWorkbenchModel -ProjectRoot $ProjectRoot -DataRoot $DataRoot -ModelId $id))}
    return $rows.ToArray()
}

Export-ModuleMember -Function Get-MLLMModelInventory,Test-MLLMWorkbenchModel,Get-MLLMActiveModel
