Set-StrictMode -Version 2
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.IO.Compression -ErrorAction Stop
Add-Type -AssemblyName System.IO.Compression.FileSystem -ErrorAction Stop

function Test-MLLMPackageHash {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)][ValidateNotNullOrEmpty()][string]$Path,
        [Parameter(Mandatory=$true)][ValidateNotNullOrEmpty()][string]$ExpectedSha256
    )
    if(-not(Test-Path -LiteralPath $Path -PathType Leaf)){return $false}
    $expected=$ExpectedSha256.ToLowerInvariant()
    if($expected -notmatch '^[0-9a-f]{64}$'){return $false}
    $actual=(Get-FileHash -LiteralPath $Path -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant()
    return ($actual -eq $expected)
}

function Expand-MLLMSafeArchive {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)][ValidateNotNullOrEmpty()][string]$ArchivePath,
        [Parameter(Mandatory=$true)][ValidateNotNullOrEmpty()][string]$Destination
    )

    if(-not(Test-Path -LiteralPath $ArchivePath -PathType Leaf)){throw "Archive missing: $ArchivePath"}
    $destFull=[IO.Path]::GetFullPath($Destination)
    if(-not(Test-Path -LiteralPath $destFull -PathType Container)){New-Item -ItemType Directory -Force -Path $destFull | Out-Null}
    $prefix=$destFull.TrimEnd([IO.Path]::DirectorySeparatorChar,[IO.Path]::AltDirectorySeparatorChar)+[IO.Path]::DirectorySeparatorChar

    $fs=[IO.File]::Open($ArchivePath,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
    $archive=New-Object IO.Compression.ZipArchive($fs,[IO.Compression.ZipArchiveMode]::Read,$false)
    $count=0
    try{
        foreach($entry in $archive.Entries){
            $name=[string]$entry.FullName
            if(-not $name){continue}
            if([IO.Path]::IsPathRooted($name)){throw "Archive entry is rooted: $name"}
            $target=[IO.Path]::GetFullPath((Join-Path $destFull $name))
            if(-not $target.StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase)){
                throw "Archive entry escapes destination: $name"
            }
            $isDirectory=$name.EndsWith('/') -or $name.EndsWith('\') -or ([string]$entry.Name -eq '')
            if($isDirectory){
                if(-not(Test-Path -LiteralPath $target -PathType Container)){New-Item -ItemType Directory -Force -Path $target | Out-Null}
                continue
            }
            $parent=Split-Path -Parent $target
            if(-not(Test-Path -LiteralPath $parent -PathType Container)){New-Item -ItemType Directory -Force -Path $parent | Out-Null}
            $input=$entry.Open()
            $output=New-Object IO.FileStream($target,[IO.FileMode]::Create,[IO.FileAccess]::Write,[IO.FileShare]::None)
            try{
                $input.CopyTo($output)
                $output.Flush($true)
            }finally{
                $output.Dispose()
                $input.Dispose()
            }
            $count++
        }
    }finally{
        $archive.Dispose()
        $fs.Dispose()
    }
    return [pscustomobject]@{status='PASS';destination=$destFull;files=$count}
}

function Test-MLLMStageContract {
    [CmdletBinding()]
    param([Parameter(Mandatory=$true)][ValidateNotNullOrEmpty()][string]$StageRoot)

    $root=[IO.Path]::GetFullPath($StageRoot)
    $required=@(
        'Start_M_LLM_Workbench.ps1',
        'Bootstrap_SafeCore.ps1',
        'M_LLM_PHYSICAL_PREFLIGHT.ps1',
        'M_LLM_GUI_PREFLIGHT.ps1'
    )
    $errors=New-Object Collections.Generic.List[string]
    $parsed=0

    if(-not(Test-Path -LiteralPath $root -PathType Container)){
        $errors.Add("Stage root missing: $root")
        return [pscustomobject]@{status='FAIL';errors=@($errors);required=@($required);parsed_count=0}
    }

    foreach($relative in $required){
        $path=Join-Path $root $relative
        if(-not(Test-Path -LiteralPath $path -PathType Leaf)){
            $errors.Add("Required stage file missing: $relative")
            continue
        }
        [byte[]]$raw=[IO.File]::ReadAllBytes($path)
        if($null -ne ($raw | Where-Object {$_ -gt 127} | Select-Object -First 1)){
            $errors.Add("Direct PS5.1 entrypoint contains non-ASCII bytes: $relative")
            continue
        }
        $tokens=$null
        $parseErrors=$null
        [void][Management.Automation.Language.Parser]::ParseFile($path,[ref]$tokens,[ref]$parseErrors)
        if(@($parseErrors).Count -gt 0){
            $errors.Add(('PS5.1 parse failed for '+$relative+': ')+((@($parseErrors)|ForEach-Object{$_.Message}) -join ' | '))
            continue
        }
        $parsed++
    }

    $status=if($errors.Count -eq 0){'PASS'}else{'FAIL'}
    return [pscustomobject]@{
        status=$status
        errors=@($errors)
        required=@($required)
        parsed_count=$parsed
        bootstrap_entrypoint=if((Test-Path -LiteralPath (Join-Path $root 'Bootstrap_SafeCore.ps1') -PathType Leaf)){'PRESENT'}else{'MISSING'}
    }
}

Export-ModuleMember -Function Test-MLLMPackageHash,Expand-MLLMSafeArchive,Test-MLLMStageContract
