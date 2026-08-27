[CmdletBinding()]
param()
$ErrorActionPreference='Stop'
Set-StrictMode -Version 2
$root=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$source=Join-Path $root 'Start_M_LLM_Workbench.cmd'
if(-not(Test-Path -LiteralPath $source -PathType Leaf)){throw "Launcher missing: $source"}

function Invoke-LauncherDryRun {
    param([bool]$WithDesktop,[string[]]$Arguments=@())
    $dir=Join-Path $env:RUNNER_TEMP ('mllm launcher test '+[guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    Copy-Item -LiteralPath $source -Destination (Join-Path $dir 'Start_M_LLM_Workbench.cmd') -Force
    if($WithDesktop){
        $desktopDir=Join-Path $dir 'desktop'
        New-Item -ItemType Directory -Force -Path $desktopDir | Out-Null
        [IO.File]::WriteAllBytes((Join-Path $desktopDir 'MLLM.Workbench.Desktop.exe'),[byte[]](0))
    }
    $old=$env:MLLM_LAUNCHER_TEST
    $env:MLLM_LAUNCHER_TEST='1'
    Push-Location $dir
    try{
        $cmd=Join-Path $dir 'Start_M_LLM_Workbench.cmd'
        $output=@(& $cmd @Arguments 2>&1 | ForEach-Object {[string]$_}) -join "`n"
        $rc=$LASTEXITCODE
        return [pscustomobject]@{ExitCode=$rc;Output=$output}
    }finally{
        Pop-Location
        if($null -eq $old){Remove-Item Env:MLLM_LAUNCHER_TEST -ErrorAction SilentlyContinue}else{$env:MLLM_LAUNCHER_TEST=$old}
        Remove-Item -LiteralPath $dir -Recurse -Force -ErrorAction SilentlyContinue
    }
}

$desktop=Invoke-LauncherDryRun -WithDesktop $true
if($desktop.ExitCode -ne 0 -or $desktop.Output -notmatch 'MLLM_LAUNCH_TARGET=DESKTOP'){throw ('Desktop route failed: '+$desktop.Output)}
$legacyMissing=Invoke-LauncherDryRun -WithDesktop $false
if($legacyMissing.ExitCode -ne 0 -or $legacyMissing.Output -notmatch 'MLLM_LAUNCH_TARGET=LEGACY'){throw ('Missing desktop fallback failed: '+$legacyMissing.Output)}
$legacyForced=Invoke-LauncherDryRun -WithDesktop $true -Arguments @('--legacy')
if($legacyForced.ExitCode -ne 0 -or $legacyForced.Output -notmatch 'MLLM_LAUNCH_TARGET=LEGACY'){throw ('Forced legacy route failed: '+$legacyForced.Output)}

Write-Host 'DESKTOP_LAUNCHER_FALLBACK=PASS desktop=PASS missing=LEGACY forced=LEGACY'
