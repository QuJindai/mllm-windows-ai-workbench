[CmdletBinding()]
param(
    [Parameter(Mandatory=$false)][string]$ProjectRoot = ''
)

$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = $PSScriptRoot
}
if ([string]::IsNullOrWhiteSpace($ProjectRoot) -and $MyInvocation.MyCommand.Path) {
    $ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
}
if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    throw 'SAFE_CORE_PROJECT_ROOT_UNRESOLVED'
}
$ProjectRoot = [System.IO.Path]::GetFullPath($ProjectRoot)

$ExpectedSha256 = '6a2e73091b27df0b711346df0b3abc39c78838a9764e03e1ec8c696cbfde3c6a'
$StampPath = Join-Path $ProjectRoot ('.safe-core-materialized-' + $ExpectedSha256 + '.stamp')
$RequiredPaths = @(
    'engine\Core.psm1',
    'engine\EmergencyDoctor.ps1',
    'gui\GuiAdapter.psm1',
    'gui\Workbench.Wpf.ps1'
)
$GuiScopeMarker = 'Import-Module (Join-Path $ProjectRoot "engine\$m.psm1") -Force -Global'

function Test-SafeCoreReady {
    if (-not (Test-Path -LiteralPath $StampPath -PathType Leaf)) { return $false }
    foreach ($relative in $RequiredPaths) {
        if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot $relative) -PathType Leaf)) { return $false }
    }
    try {
        $adapterText = Get-Content -LiteralPath (Join-Path $ProjectRoot 'gui\GuiAdapter.psm1') -Raw -Encoding UTF8
        if (-not $adapterText.Contains($GuiScopeMarker)) { return $false }
    } catch { return $false }
    return $true
}

if (Test-SafeCoreReady) {
    Write-Host 'SAFE_CORE_BOOTSTRAP=READY'
    return
}

$overlayDir = Join-Path $ProjectRoot 'ci\overlay'
$parts = @(Get-ChildItem -LiteralPath $overlayDir -Filter 'chunk*.b64' -File -ErrorAction Stop | Sort-Object Name)
if ($parts.Count -lt 1) { throw 'SAFE_CORE_OVERLAY_PARTS_MISSING' }

$builder = New-Object System.Text.StringBuilder
foreach ($part in $parts) {
    $piece = (Get-Content -LiteralPath $part.FullName -Raw -Encoding ASCII).Trim()
    [void]$builder.Append($piece)
}
$encoded = $builder.ToString()
try {
    [byte[]]$raw = [System.Convert]::FromBase64String($encoded)
} catch {
    throw ('SAFE_CORE_OVERLAY_BASE64_INVALID: ' + $_.Exception.Message)
}

$sha = [System.Security.Cryptography.SHA256]::Create()
try {
    $hashBytes = $sha.ComputeHash($raw)
} finally {
    $sha.Dispose()
}
$actualSha256 = -join ($hashBytes | ForEach-Object { $_.ToString('x2') })
if ($actualSha256 -ne $ExpectedSha256) {
    throw "SAFE_CORE_OVERLAY_SHA256_MISMATCH expected=$ExpectedSha256 actual=$actualSha256"
}

Add-Type -AssemblyName System.IO.Compression -ErrorAction Stop
Add-Type -AssemblyName System.IO.Compression.FileSystem -ErrorAction Stop
$tempZip = Join-Path $ProjectRoot ('.safe-core-overlay-' + [guid]::NewGuid().ToString('N') + '.zip')
[System.IO.File]::WriteAllBytes($tempZip, $raw)

$rootFull = [System.IO.Path]::GetFullPath($ProjectRoot)
$rootPrefix = $rootFull.TrimEnd([char[]]@('\','/')) + [System.IO.Path]::DirectorySeparatorChar
$archive = $null
try {
    $archive = [System.IO.Compression.ZipFile]::OpenRead($tempZip)
    foreach ($entry in $archive.Entries) {
        $relative = $entry.FullName.Replace('/', [System.IO.Path]::DirectorySeparatorChar)
        $target = [System.IO.Path]::GetFullPath((Join-Path $ProjectRoot $relative))
        if (($target -ne $rootFull) -and (-not $target.StartsWith($rootPrefix, [System.StringComparison]::OrdinalIgnoreCase))) {
            throw "SAFE_CORE_OVERLAY_UNSAFE_PATH member=$($entry.FullName)"
        }

        if ([string]::IsNullOrEmpty($entry.Name)) {
            [void][System.IO.Directory]::CreateDirectory($target)
            continue
        }

        $parent = [System.IO.Path]::GetDirectoryName($target)
        if ($parent) { [void][System.IO.Directory]::CreateDirectory($parent) }
        $inputStream = $entry.Open()
        try {
            $outputStream = [System.IO.File]::Open($target, [System.IO.FileMode]::Create, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
            try {
                $inputStream.CopyTo($outputStream)
            } finally {
                $outputStream.Dispose()
            }
        } finally {
            $inputStream.Dispose()
        }
    }
} finally {
    if ($archive) { $archive.Dispose() }
    Remove-Item -LiteralPath $tempZip -Force -ErrorAction SilentlyContinue
}

# GuiAdapter is a module and Core dot-sources task handlers in Core's module
# scope. Shared engine modules imported only as GuiAdapter siblings are not
# visible to those handler scriptblocks. Keep Core local to GuiAdapter but
# expose State/Detection/Runtime/etc. globally, matching the CLI topology.
$guiAdapterPath = Join-Path $ProjectRoot 'gui\GuiAdapter.psm1'
$guiText = Get-Content -LiteralPath $guiAdapterPath -Raw -Encoding UTF8
$guiOldForeach = "    foreach(`$m in @('Core','State','Detection','Network','Download','Security','Evidence','Runtime')){"
$guiNewForeach = "    foreach(`$m in @('State','Detection','Network','Download','Security','Evidence','Runtime')){"
$guiOldImport = '        Import-Module (Join-Path $ProjectRoot "engine\$m.psm1") -Force'
$guiNewImport = '        Import-Module (Join-Path $ProjectRoot "engine\$m.psm1") -Force -Global'
$guiOldTasks = '    Import-MLLMTasks -ProjectRoot $ProjectRoot'
$guiNewTasks = "    Import-Module (Join-Path `$ProjectRoot 'engine\Core.psm1') -Force`r`n    Import-MLLMTasks -ProjectRoot `$ProjectRoot"
if ($guiText.Contains($guiOldForeach)) {
    $guiText = $guiText.Replace($guiOldForeach, $guiNewForeach)
    if (-not $guiText.Contains($guiOldImport)) { throw 'SAFE_CORE_GUI_SCOPE_IMPORT_TARGET_MISSING' }
    $guiText = $guiText.Replace($guiOldImport, $guiNewImport)
    if (-not $guiText.Contains($guiOldTasks)) { throw 'SAFE_CORE_GUI_SCOPE_TASK_TARGET_MISSING' }
    $guiText = $guiText.Replace($guiOldTasks, $guiNewTasks)
} elseif ((-not $guiText.Contains($GuiScopeMarker)) -or (-not $guiText.Contains("engine\Core.psm1'))) -or (-not $guiText.Contains($guiNewForeach))) {
    throw 'SAFE_CORE_GUI_SCOPE_PATCH_TARGET_MISSING'
}
Set-Content -LiteralPath $guiAdapterPath -Value $guiText -Encoding UTF8 -NoNewline

# Keep raw-checkout behavior identical to the validated CI materializer until
# the next source bundle includes these PowerShell 5.1 fixes directly.
$wpfPath = Join-Path $ProjectRoot 'gui\Workbench.Wpf.ps1'
$wpfText = Get-Content -LiteralPath $wpfPath -Raw -Encoding UTF8
$wpfOld = '{"http://$_`:$($st.runtime.web.port)"}'
$wpfNew = "{ 'http://' + [string]`$_ + ':' + [string](`$st.runtime.web.port) }"
if ($wpfText.Contains($wpfOld)) {
    $wpfText = $wpfText.Replace($wpfOld, $wpfNew)
} elseif (-not $wpfText.Contains($wpfNew)) {
    throw 'SAFE_CORE_PS51_PATCH_TARGET_MISSING'
}
Set-Content -LiteralPath $wpfPath -Value $wpfText -Encoding UTF8 -NoNewline

$doctorPath = Join-Path $ProjectRoot 'engine\EmergencyDoctor.ps1'
$doctorText = Get-Content -LiteralPath $doctorPath -Raw -Encoding UTF8
$doctorPatches = @(
    @('        checks=@($checks)', '        checks=$checks.ToArray()'),
    @('    [pscustomobject]@{checks=@($checks);evidence_dir=$evidenceDir;json=$jsonPath;text=$txtPath}', '    [pscustomobject]@{checks=$checks.ToArray();evidence_dir=$evidenceDir;json=$jsonPath;text=$txtPath}')
)
foreach ($patch in $doctorPatches) {
    if ($doctorText.Contains($patch[0])) {
        $doctorText = $doctorText.Replace($patch[0], $patch[1])
    } elseif (-not $doctorText.Contains($patch[1])) {
        throw 'SAFE_CORE_PS51_EMERGENCY_DOCTOR_PATCH_TARGET_MISSING'
    }
}
Set-Content -LiteralPath $doctorPath -Value $doctorText -Encoding UTF8 -NoNewline

$corePath = Join-Path $ProjectRoot 'engine\Core.psm1'
$coreText = Get-Content -LiteralPath $corePath -Raw -Encoding UTF8
$coreOldCrLf = "    ,`$results.ToArray()`r`n"
$coreNewCrLf = "    `$results.ToArray()`r`n"
$coreOldLf = "    ,`$results.ToArray()`n"
$coreNewLf = "    `$results.ToArray()`n"
if ($coreText.Contains($coreOldCrLf)) {
    $coreText = $coreText.Replace($coreOldCrLf, $coreNewCrLf)
} elseif ($coreText.Contains($coreOldLf)) {
    $coreText = $coreText.Replace($coreOldLf, $coreNewLf)
} elseif ((-not $coreText.Contains($coreNewCrLf)) -and (-not $coreText.Contains($coreNewLf))) {
    throw 'SAFE_CORE_DOCTOR_ARRAY_SHAPE_PATCH_TARGET_MISSING'
}
Set-Content -LiteralPath $corePath -Value $coreText -Encoding UTF8 -NoNewline

Set-Content -LiteralPath $StampPath -Value ("sha256=$actualSha256`r`nmaterialized=" + (Get-Date -Format o)) -Encoding ASCII

if (-not (Test-SafeCoreReady)) { throw 'SAFE_CORE_BOOTSTRAP_INCOMPLETE' }
Write-Host "SAFE_CORE_BOOTSTRAP=PASS parts=$($parts.Count) sha256=$actualSha256"
