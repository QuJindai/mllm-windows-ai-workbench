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

function Assert-Route {
    param([string]$Name,[string]$Expected,[string[]]$Arguments=@(),[bool]$WithDesktop=$true)
    $result=Invoke-LauncherDryRun -WithDesktop $WithDesktop -Arguments $Arguments
    if($result.ExitCode -ne 0 -or $result.Output -notmatch ('MLLM_LAUNCH_TARGET='+$Expected)){
        throw ("Launcher route failed case=$Name expected=$Expected output="+$result.Output)
    }
}

Assert-Route -Name 'default desktop' -Expected 'DESKTOP'
Assert-Route -Name 'explicit gui stays desktop' -Expected 'DESKTOP' -Arguments @('--gui')
Assert-Route -Name 'missing desktop' -Expected 'LEGACY' -WithDesktop $false
Assert-Route -Name 'forced legacy' -Expected 'LEGACY' -Arguments @('--legacy')

# These switches existed before the native Desktop shell. They are operational
# commands, not Desktop UI arguments, and must keep reaching the legacy
# PowerShell entrypoint after the Desktop executable is shipped.
foreach($case in @(
    [pscustomobject]@{Name='cli';Args=@('--cli')},
    [pscustomobject]@{Name='doctor';Args=@('--doctor')},
    [pscustomobject]@{Name='start service';Args=@('--start-service')},
    [pscustomobject]@{Name='stop service';Args=@('--stop-service')},
    [pscustomobject]@{Name='start web';Args=@('--start-web')},
    [pscustomobject]@{Name='stop web';Args=@('--stop-web')},
    [pscustomobject]@{Name='preset';Args=@('--preset','Core')},
    [pscustomobject]@{Name='network mode';Args=@('--network-mode','ONLINE_GLOBAL')}
)){
    Assert-Route -Name $case.Name -Expected 'LEGACY' -Arguments @($case.Args)
}

Write-Host 'DESKTOP_LAUNCHER_FALLBACK=PASS desktop=PASS gui=DESKTOP missing=LEGACY forced=LEGACY legacy_commands=PASS'
