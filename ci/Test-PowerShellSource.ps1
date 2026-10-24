# ASCII-only: this gate itself must run on both Windows PowerShell hosts.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('Legacy51', 'PowerShell7')]
    [string]$RuntimeGroup,
    [string]$SourceRoot = ''
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2
$version = $PSVersionTable.PSVersion
if (($RuntimeGroup -eq 'Legacy51' -and ($version.Major -ne 5 -or $version.Minor -ne 1)) -or
    ($RuntimeGroup -eq 'PowerShell7' -and $version.Major -lt 7)) {
    throw "POWERSHELL_RUNTIME_MISMATCH: group=$RuntimeGroup actual=$version"
}

if ([string]::IsNullOrWhiteSpace($SourceRoot)) { $SourceRoot = Join-Path $PSScriptRoot '..' }
$root = (Resolve-Path -LiteralPath $SourceRoot).Path.TrimEnd('\', '/')
$sources = @{}
Get-ChildItem -LiteralPath $root -Recurse -File | Where-Object {
    $_.Extension -in @('.ps1', '.psm1')
} | ForEach-Object {
    $relative = $_.FullName.Substring($root.Length + 1).Replace('\', '/')
    # Preserve the existing generated-dist exclusion, matching a path segment.
    if ($relative -notmatch '(^|/)dist/') { $sources[$relative] = $_.FullName }
}

$modernOnly = @{}
try {
    $manifestPath = Join-Path $root 'ci/powershell-runtimes.json'
    $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if (($manifest.schemaVersion -isnot [int] -and $manifest.schemaVersion -isnot [long]) -or
        $manifest.schemaVersion -ne 1 -or $manifest.powershell7 -isnot [array] -or
        $manifest.powershell7.Count -eq 0) { throw 'Invalid schema or empty list' }
    foreach ($relative in $manifest.powershell7) {
        if ($relative -isnot [string] -or $relative -notmatch '^[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*\.ps(?:1|m1)$' -or
            $relative -match '(^|/)\.\.?(/|$)' -or $modernOnly.ContainsKey($relative) -or
            -not $sources.ContainsKey($relative)) { throw "Invalid or missing source: $relative" }
        $modernOnly[$relative] = $true
    }
} catch {
    throw "POWERSHELL_RUNTIME_MANIFEST_INVALID: $($_.Exception.Message)"
}

$checked = @()
$otherRuntime = @()
$errors = @()
foreach ($relative in @($sources.Keys | Sort-Object)) {
    if ($RuntimeGroup -eq 'Legacy51' -and $modernOnly.ContainsKey($relative)) {
        $otherRuntime += $relative
        continue
    }
    $tokens = $null
    $parseErrors = $null
    # ParseFile intentionally keeps the selected host's real decoding behaviour.
    # Never invoke/import source during a syntax check. PS7 checks ALL sources,
    # so a modern-only exclusion cannot remove a file from both gates.
    $ast = [Management.Automation.Language.Parser]::ParseFile($sources[$relative], [ref]$tokens, [ref]$parseErrors)
    foreach ($parseError in @($parseErrors)) {
        $errors += "${relative}:$($parseError.Extent.StartLineNumber): $($parseError.Message)"
    }
    if ($null -ne $ast.ScriptRequirements -and $null -ne $ast.ScriptRequirements.RequiredPSVersion -and
        $ast.ScriptRequirements.RequiredPSVersion -gt $version) {
        $errors += "${relative}: requires PowerShell $($ast.ScriptRequirements.RequiredPSVersion), actual $version"
    }
    $checked += $relative
}
if ($checked.Count -eq 0) { throw 'POWERSHELL_SOURCE_PARSE_FAILED: no source files checked' }
if ($errors.Count -gt 0) { throw ("POWERSHELL_SOURCE_PARSE_FAILED:`n" + ($errors -join "`n")) }
[ordered]@{
    runtimeGroup = $RuntimeGroup
    powerShellVersion = $version.ToString()
    checkedFiles = @($checked)
    otherRuntimeFiles = @($otherRuntime)
} | ConvertTo-Json -Depth 4
