Set-StrictMode -Version 2
$ErrorActionPreference='Stop'

$validationModule=Join-Path $PSScriptRoot 'PackageValidation.psm1'
if(-not(Get-Command Test-MLLMStageContract -ErrorAction SilentlyContinue)){
    if(-not(Test-Path -LiteralPath $validationModule -PathType Leaf)){throw 'PackageValidation.psm1 missing'}
    Import-Module $validationModule -Force -ErrorAction Stop
}

function Save-MLLMActivePointer {
    param(
        [Parameter(Mandatory=$true)]$Pointer,
        [Parameter(Mandatory=$true)][string]$PointerPath
    )
    $full=[IO.Path]::GetFullPath($PointerPath)
    $dir=Split-Path -Parent $full
    if(-not(Test-Path -LiteralPath $dir -PathType Container)){New-Item -ItemType Directory -Force -Path $dir | Out-Null}
    $tmp=$full+'.tmp'
    $backup=$full+'.bak'
    $utf8=New-Object Text.UTF8Encoding($false)
    [IO.File]::WriteAllText($tmp,($Pointer | ConvertTo-Json -Depth 10),$utf8)
    try{
        if(Test-Path -LiteralPath $full -PathType Leaf){
            if(Test-Path -LiteralPath $backup -PathType Leaf){Remove-Item -LiteralPath $backup -Force}
            [IO.File]::Replace($tmp,$full,$backup,$true)
            if(Test-Path -LiteralPath $backup -PathType Leaf){Remove-Item -LiteralPath $backup -Force}
        }else{
            Move-Item -LiteralPath $tmp -Destination $full -Force
        }
    }catch{
        if(Test-Path -LiteralPath $tmp -PathType Leaf){Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue}
        if(Test-Path -LiteralPath $backup -PathType Leaf){Remove-Item -LiteralPath $backup -Force -ErrorAction SilentlyContinue}
        throw
    }
    return $full
}

function Test-MLLMInstalledVersion {
    [CmdletBinding()]
    param([Parameter(Mandatory=$true)][ValidateNotNullOrEmpty()][string]$VersionRoot)

    $contract=Test-MLLMStageContract -StageRoot $VersionRoot
    if([string]$contract.status -ne 'PASS'){
        return [pscustomobject]@{
            status='FAIL'
            version_path=[IO.Path]::GetFullPath($VersionRoot)
            errors=@($contract.errors)
        }
    }
    return [pscustomobject]@{
        status='PASS'
        version_path=[IO.Path]::GetFullPath($VersionRoot)
        errors=@()
        parsed_count=[int]$contract.parsed_count
    }
}

function Install-MLLMVersion {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)][ValidateNotNullOrEmpty()][string]$StageRoot,
        [Parameter(Mandatory=$true)][ValidateNotNullOrEmpty()][string]$VersionRoot
    )

    $source=[IO.Path]::GetFullPath($StageRoot)
    $target=[IO.Path]::GetFullPath($VersionRoot)
    $stageCheck=Test-MLLMStageContract -StageRoot $source
    if([string]$stageCheck.status -ne 'PASS'){
        throw ('Stage contract failed: '+(@($stageCheck.errors) -join ' | '))
    }

    if(Test-Path -LiteralPath $target -PathType Container){
        $existing=Test-MLLMInstalledVersion -VersionRoot $target
        if([string]$existing.status -eq 'PASS'){
            return [pscustomobject]@{status='PASS';version_path=$target;reused=$true;repair_path=$null}
        }
        $target=$target+'.repair.'+(Get-Date -Format 'yyyyMMdd_HHmmss_fff')+'.'+([guid]::NewGuid().ToString('N').Substring(0,8))
    }

    $parent=Split-Path -Parent $target
    if(-not(Test-Path -LiteralPath $parent -PathType Container)){New-Item -ItemType Directory -Force -Path $parent | Out-Null}
    New-Item -ItemType Directory -Force -Path $target | Out-Null
    try{
        foreach($item in Get-ChildItem -LiteralPath $source -Force){
            Copy-Item -LiteralPath $item.FullName -Destination $target -Recurse -Force -ErrorAction Stop
        }
        $verify=Test-MLLMInstalledVersion -VersionRoot $target
        if([string]$verify.status -ne 'PASS'){
            throw ('Installed version verification failed: '+(@($verify.errors) -join ' | '))
        }
        return [pscustomobject]@{status='PASS';version_path=$target;reused=$false;repair_path=if($target -ne [IO.Path]::GetFullPath($VersionRoot)){$target}else{$null}}
    }catch{
        if(Test-Path -LiteralPath $target -PathType Container){
            Remove-Item -LiteralPath $target -Recurse -Force -ErrorAction SilentlyContinue
        }
        throw
    }
}

function Get-MLLMActiveVersion {
    [CmdletBinding()]
    param([Parameter(Mandatory=$true)][ValidateNotNullOrEmpty()][string]$PointerPath)
    if(-not(Test-Path -LiteralPath $PointerPath -PathType Leaf)){return $null}
    $raw=Get-Content -LiteralPath $PointerPath -Raw -Encoding UTF8
    if(-not $raw){throw "Active version pointer is empty: $PointerPath"}
    $pointer=$raw | ConvertFrom-Json
    if([string]$pointer.schema -ne 'mllm.universal-installer.current.v1'){throw "Unsupported active pointer schema: $($pointer.schema)"}
    return $pointer
}

function Set-MLLMActiveVersion {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)][ValidateNotNullOrEmpty()][string]$PointerPath,
        [Parameter(Mandatory=$true)][ValidateNotNullOrEmpty()][string]$VersionId,
        [Parameter(Mandatory=$true)][ValidateNotNullOrEmpty()][string]$VersionPath,
        $Previous=$null
    )

    $check=Test-MLLMInstalledVersion -VersionRoot $VersionPath
    if([string]$check.status -ne 'PASS'){
        throw ('Refusing to activate invalid version: '+(@($check.errors) -join ' | '))
    }

    $previousValue=$null
    if($null -ne $Previous){
        if($null -ne $Previous.PSObject.Properties['version_id'] -and $null -ne $Previous.PSObject.Properties['version_path']){
            $previousValue=[ordered]@{version_id=[string]$Previous.version_id;version_path=[string]$Previous.version_path}
        }
    }
    $pointer=[ordered]@{
        schema='mllm.universal-installer.current.v1'
        version_id=$VersionId
        version_path=[IO.Path]::GetFullPath($VersionPath)
        previous_version=$previousValue
        activated_at=(Get-Date).ToString('o')
    }
    Save-MLLMActivePointer -Pointer $pointer -PointerPath $PointerPath | Out-Null
    return (Get-MLLMActiveVersion -PointerPath $PointerPath)
}

function Invoke-MLLMRollback {
    [CmdletBinding()]
    param([Parameter(Mandatory=$true)][ValidateNotNullOrEmpty()][string]$PointerPath)

    $current=Get-MLLMActiveVersion -PointerPath $PointerPath
    if($null -eq $current){throw 'No active version to roll back'}
    $previous=$current.previous_version
    if($null -eq $previous){throw 'No previous version recorded for rollback'}
    $previousCheck=Test-MLLMInstalledVersion -VersionRoot ([string]$previous.version_path)
    if([string]$previousCheck.status -ne 'PASS'){
        throw ('Previous version is invalid; rollback refused: '+(@($previousCheck.errors) -join ' | '))
    }
    return Set-MLLMActiveVersion -PointerPath $PointerPath -VersionId ([string]$previous.version_id) -VersionPath ([string]$previous.version_path) -Previous $current
}

Export-ModuleMember -Function Install-MLLMVersion,Test-MLLMInstalledVersion,Get-MLLMActiveVersion,Set-MLLMActiveVersion,Invoke-MLLMRollback
