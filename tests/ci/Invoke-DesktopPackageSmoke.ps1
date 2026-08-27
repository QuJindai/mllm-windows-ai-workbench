[CmdletBinding()]
param()
$ErrorActionPreference='Stop'
Set-StrictMode -Version 2
$root=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$packageScript=Join-Path $root 'ci\package_desktop_phase_a.ps1'
if(-not(Test-Path -LiteralPath $packageScript -PathType Leaf)){throw "Desktop package script missing: $packageScript"}

$outputRoot=Join-Path $env:RUNNER_TEMP ('mllm desktop package output '+[guid]::NewGuid().ToString('N'))
$extractRoot=Join-Path $env:RUNNER_TEMP ('mllm desktop package extract '+[guid]::NewGuid().ToString('N'))
try{
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $packageScript -OutputRoot $outputRoot
    if($LASTEXITCODE -ne 0){throw "Desktop packaging failed rc=$LASTEXITCODE"}

    $zip=Join-Path $outputRoot 'MLLM_WORKBENCH_DESKTOP_PHASE_A_win-x64.zip'
    $shaFile=$zip+'.sha256'
    if(-not(Test-Path -LiteralPath $zip -PathType Leaf)){throw "Desktop package ZIP missing: $zip"}
    if(-not(Test-Path -LiteralPath $shaFile -PathType Leaf)){throw "Desktop package SHA file missing: $shaFile"}
    $expected=((Get-Content -LiteralPath $shaFile -Raw).Trim() -split '\s+')[0].ToLowerInvariant()
    $actual=(Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant()
    if($expected -ne $actual){throw "Desktop package SHA256 mismatch expected=$expected actual=$actual"}

    Expand-Archive -LiteralPath $zip -DestinationPath $extractRoot -Force
    $required=@(
        'desktop\MLLM.Workbench.Desktop.exe',
        'runtime\WorkbenchBackend.ps1',
        'Bootstrap_SafeCore.ps1',
        'ci\overlay\chunk01.b64',
        'engine\Core.psm1',
        'gui\GuiAdapter.psm1',
        'installer\Start-UniversalInstaller.ps1',
        'config\source-manifest.json',
        'Start_M_LLM_Workbench.cmd',
        'Start_M_LLM_Workbench.ps1'
    )
    foreach($relative in $required){
        $full=Join-Path $extractRoot $relative
        if(-not(Test-Path -LiteralPath $full -PathType Leaf)){throw "Desktop package required file missing: $relative"}
    }
    $stamps=@(Get-ChildItem -LiteralPath $extractRoot -Force -File | Where-Object {$_.Name -like '.safe-core-materialized-*.stamp'})
    if($stamps.Count -ne 1){throw "Packaged Safe Core materialization stamp missing or ambiguous: count=$($stamps.Count)"}

    $exe=Join-Path $extractRoot 'desktop\MLLM.Workbench.Desktop.exe'
    $process=Start-Process -FilePath $exe -ArgumentList @('--smoke') -PassThru
    if(-not $process.WaitForExit(60000)){
        try{$process.Kill()}catch{}
        throw 'Desktop --smoke exceeded 60 seconds'
    }
    if($process.ExitCode -ne 0){throw "Desktop --smoke failed rc=$($process.ExitCode)"}

    $old=$env:MLLM_LAUNCHER_TEST
    $env:MLLM_LAUNCHER_TEST='1'
    try{
        $launcher=Join-Path $extractRoot 'Start_M_LLM_Workbench.cmd'
        $launcherOutput=@(& $launcher 2>&1 | ForEach-Object {[string]$_}) -join "`n"
        if($LASTEXITCODE -ne 0 -or $launcherOutput -notmatch 'MLLM_LAUNCH_TARGET=DESKTOP'){
            throw ('Packaged launcher did not select Desktop: '+$launcherOutput)
        }
    }finally{
        if($null -eq $old){Remove-Item Env:MLLM_LAUNCHER_TEST -ErrorAction SilentlyContinue}else{$env:MLLM_LAUNCHER_TEST=$old}
    }

    $zipInfo=Get-Item -LiteralPath $zip
    Write-Host "DESKTOP_PACKAGE_SMOKE=PASS bytes=$($zipInfo.Length) sha256=$actual pre_materialized=PASS self_contained=PASS backend=PASS launcher=DESKTOP"
}finally{
    Remove-Item -LiteralPath $extractRoot -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $outputRoot -Recurse -Force -ErrorAction SilentlyContinue
}
