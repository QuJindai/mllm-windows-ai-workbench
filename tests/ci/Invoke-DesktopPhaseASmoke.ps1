[CmdletBinding()]
param()

$ErrorActionPreference='Stop'
Set-StrictMode -Version 2

$root=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$packageScript=Join-Path $root 'ci\package_desktop_phase_a.ps1'
if(-not(Test-Path -LiteralPath $packageScript -PathType Leaf)){throw "Desktop package script missing: $packageScript"}

function Get-FileFingerprint {
    param([Parameter(Mandatory=$true)][string]$Path)
    $exists=Test-Path -LiteralPath $Path -PathType Leaf
    return [pscustomobject]@{
        path=$Path
        exists=[bool]$exists
        sha256=if($exists){(Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()}else{$null}
    }
}

function Assert-FingerprintUnchanged {
    param($Before,$After,[string]$Name)
    if([bool]$Before.exists -ne [bool]$After.exists){throw "$Name existence changed during non-installing E2E"}
    if([string]$Before.sha256 -ne [string]$After.sha256){throw "$Name SHA256 changed during non-installing E2E"}
}

function Invoke-RpcRequest {
    param(
        [Parameter(Mandatory=$true)]$Writer,
        [Parameter(Mandatory=$true)]$Reader,
        [Parameter(Mandatory=$true)][string]$Token,
        [Parameter(Mandatory=$true)][string]$Method
    )
    $id=[guid]::NewGuid().ToString('N')
    $request=[ordered]@{
        protocol='1.0'
        type='request'
        id=$id
        sessionToken=$Token
        method=$Method
        payload=$null
    }
    $Writer.WriteLine(($request | ConvertTo-Json -Depth 8 -Compress))
    $Writer.Flush()
    $line=$Reader.ReadLine()
    if(-not $line){throw "RPC response missing for method: $Method"}
    $response=$line | ConvertFrom-Json
    if([string]$response.id -ne $id){throw "RPC response id mismatch for method: $Method"}
    if(-not [bool]$response.success){
        $message=if($null -ne $response.error){[string]$response.error.message}else{'unknown backend error'}
        throw "RPC method failed method=$Method error=$message"
    }
    return $response.payload
}

$outputRoot=Join-Path $env:RUNNER_TEMP ('mllm phase a e2e package '+[guid]::NewGuid().ToString('N'))
$extractRoot=Join-Path $env:RUNNER_TEMP ('mllm phase a e2e extract '+[guid]::NewGuid().ToString('N'))
$dataRoot=Join-Path $env:RUNNER_TEMP ('mllm phase a e2e data '+[guid]::NewGuid().ToString('N'))
$guiDataRoot=Join-Path $env:RUNNER_TEMP ('mllm phase a gui preflight '+[guid]::NewGuid().ToString('N'))
$backendOut=Join-Path $env:RUNNER_TEMP ('mllm-phase-a-backend-'+[guid]::NewGuid().ToString('N')+'.out.txt')
$backendErr=Join-Path $env:RUNNER_TEMP ('mllm-phase-a-backend-'+[guid]::NewGuid().ToString('N')+'.err.txt')

$installerStatePath=Join-Path $env:ProgramData 'M-LLM\Installer\state\installer_state.json'
$currentPointerPath=Join-Path $env:ProgramData 'M-LLM\Workbench\current.json'
$stateBefore=Get-FileFingerprint -Path $installerStatePath
$pointerBefore=Get-FileFingerprint -Path $currentPointerPath
$backendProcess=$null
$client=$null
$reader=$null
$writer=$null

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

    # Recreate a raw Safe Core foundation inside the extracted package. The
    # bootstrap must be able to restore engine/gui from the signed overlay.
    Get-ChildItem -LiteralPath $extractRoot -Force -File -ErrorAction SilentlyContinue |
        Where-Object {$_.Name -like '.safe-core-materialized-*.stamp'} |
        Remove-Item -Force -ErrorAction Stop
    foreach($relativeDir in @('engine','gui')){
        $target=Join-Path $extractRoot $relativeDir
        if(Test-Path -LiteralPath $target -PathType Container){Remove-Item -LiteralPath $target -Recurse -Force}
    }

    $bootstrap=Join-Path $extractRoot 'Bootstrap_SafeCore.ps1'
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $bootstrap -ProjectRoot $extractRoot
    if($LASTEXITCODE -ne 0){throw "Raw Safe Core bootstrap failed rc=$LASTEXITCODE"}
    foreach($relative in @('engine\Core.psm1','gui\GuiAdapter.psm1')){
        if(-not(Test-Path -LiteralPath (Join-Path $extractRoot $relative) -PathType Leaf)){throw "Bootstrap did not restore: $relative"}
    }
    $stamps=@(Get-ChildItem -LiteralPath $extractRoot -Force -File | Where-Object {$_.Name -like '.safe-core-materialized-*.stamp'})
    if($stamps.Count -ne 1){throw "Bootstrap materialization stamp count is invalid: $($stamps.Count)"}

    # Start the packaged desktop without creating a window. --smoke performs
    # a real backend launch, authenticated pipe handshake and system.ping.
    $desktopExe=Join-Path $extractRoot 'desktop\MLLM.Workbench.Desktop.exe'
    if(-not(Test-Path -LiteralPath $desktopExe -PathType Leaf)){throw "Packaged desktop executable missing: $desktopExe"}
    $desktop=Start-Process -FilePath $desktopExe -ArgumentList @('--smoke') -PassThru
    if(-not $desktop.WaitForExit(60000)){
        try{$desktop.Kill()}catch{}
        throw 'Packaged Desktop --smoke exceeded 60 seconds'
    }
    if($desktop.ExitCode -ne 0){throw "Packaged Desktop --smoke failed rc=$($desktop.ExitCode)"}

    # Run the non-installing GUI preflight from the extracted package.
    $guiPreflight=Join-Path $extractRoot 'M_LLM_GUI_PREFLIGHT.ps1'
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $guiPreflight -DataRoot $guiDataRoot -NetworkMode OFFLINE_CACHE
    if($LASTEXITCODE -ne 0){throw "Packaged GUI preflight failed rc=$LASTEXITCODE"}
    $guiReportPath=Join-Path $guiDataRoot 'gui_preflight.json'
    if(-not(Test-Path -LiteralPath $guiReportPath -PathType Leaf)){throw 'GUI preflight report missing'}
    $guiReport=Get-Content -LiteralPath $guiReportPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if([string]$guiReport.status -ne 'PASS'){throw "GUI preflight report status is not PASS: $($guiReport.status)"}
    if([bool]$guiReport.core_install_authorized){throw 'GUI preflight unexpectedly authorized Core installation'}
    if([int]$guiReport.install_actions_executed -ne 0){throw 'GUI preflight executed installation actions'}
    if([int]$guiReport.network_actions_executed -ne 0){throw 'GUI preflight executed network actions'}

    # Start the packaged backend directly and exercise all Phase A read-only
    # snapshot methods over the authenticated named pipe.
    $pipeName='mllm-phase-a-e2e-'+[guid]::NewGuid().ToString('N')
    $token=[guid]::NewGuid().ToString('N')+[guid]::NewGuid().ToString('N')
    $backend=Join-Path $extractRoot 'runtime\WorkbenchBackend.ps1'
    $backendArgs=@(
        '-NoProfile','-ExecutionPolicy','Bypass','-File',$backend,
        '-PipeName',$pipeName,
        '-SessionToken',$token,
        '-ProtocolVersion','1.0',
        '-ProjectRoot',$extractRoot,
        '-DataRoot',$dataRoot,
        '-NetworkMode','OFFLINE_CACHE'
    )
    $backendProcess=Start-Process -FilePath 'powershell.exe' -ArgumentList $backendArgs -PassThru -RedirectStandardOutput $backendOut -RedirectStandardError $backendErr

    $client=New-Object System.IO.Pipes.NamedPipeClientStream -ArgumentList @('.', $pipeName, [System.IO.Pipes.PipeDirection]::InOut, [System.IO.Pipes.PipeOptions]::None)
    $client.Connect(15000)
    $utf8=New-Object System.Text.UTF8Encoding($false)
    $reader=New-Object System.IO.StreamReader -ArgumentList @($client,$utf8,$false,4096,$true)
    $writer=New-Object System.IO.StreamWriter -ArgumentList @($client,$utf8,4096,$true)
    $writer.AutoFlush=$true

    $handshakeId=[guid]::NewGuid().ToString('N')
    $handshake=[ordered]@{protocol='1.0';type='handshake';id=$handshakeId;sessionToken=$token}
    $writer.WriteLine(($handshake | ConvertTo-Json -Depth 6 -Compress))
    $writer.Flush()
    $handshakeLine=$reader.ReadLine()
    if(-not $handshakeLine){throw 'Backend handshake response missing'}
    $handshakeResponse=$handshakeLine | ConvertFrom-Json
    if(-not [bool]$handshakeResponse.success){throw 'Backend handshake RPC failed'}
    if(-not [bool]$handshakeResponse.payload.accepted){throw "Backend handshake rejected: $($handshakeResponse.payload.error)"}

    $dashboard=Invoke-RpcRequest -Writer $writer -Reader $reader -Token $token -Method 'dashboard.snapshot'
    if([string]$dashboard.networkMode -ne 'OFFLINE_CACHE'){throw "Dashboard network mode mismatch: $($dashboard.networkMode)"}
    if(@($dashboard.components).Count -lt 6){throw "Dashboard component count is too small: $(@($dashboard.components).Count)"}

    $doctor=Invoke-RpcRequest -Writer $writer -Reader $reader -Token $token -Method 'doctor.snapshot'
    if(@($doctor.components).Count -lt 6){throw "Doctor component count is too small: $(@($doctor.components).Count)"}

    $installer=Invoke-RpcRequest -Writer $writer -Reader $reader -Token $token -Method 'installer.snapshot'
    if([string]::IsNullOrWhiteSpace([string]$installer.stage)){throw 'Installer snapshot stage is empty'}
    if([string]::IsNullOrWhiteSpace([string]$installer.evidenceRoot)){throw 'Installer snapshot evidenceRoot is empty'}

    $writer.Dispose();$writer=$null
    $reader.Dispose();$reader=$null
    $client.Dispose();$client=$null
    if(-not $backendProcess.WaitForExit(15000)){
        try{$backendProcess.Kill()}catch{}
        throw 'Packaged backend did not stop after pipe disconnect'
    }
    if($backendProcess.ExitCode -ne 0){
        $outText=Get-Content -LiteralPath $backendOut -Raw -ErrorAction SilentlyContinue
        $errText=Get-Content -LiteralPath $backendErr -Raw -ErrorAction SilentlyContinue
        throw "Packaged backend exited rc=$($backendProcess.ExitCode) output=$outText error=$errText"
    }
    $backendProcess=$null

    # Verify desktop-first and explicit legacy launch selection from the same
    # extracted package without starting a user-facing window.
    $oldLauncherTest=$env:MLLM_LAUNCHER_TEST
    $env:MLLM_LAUNCHER_TEST='1'
    try{
        $launcher=Join-Path $extractRoot 'Start_M_LLM_Workbench.cmd'
        $desktopTarget=@(& $launcher 2>&1 | ForEach-Object {[string]$_}) -join "`n"
        if($LASTEXITCODE -ne 0 -or $desktopTarget -notmatch 'MLLM_LAUNCH_TARGET=DESKTOP'){throw "Launcher did not select Desktop: $desktopTarget"}
        $legacyTarget=@(& $launcher --legacy 2>&1 | ForEach-Object {[string]$_}) -join "`n"
        if($LASTEXITCODE -ne 0 -or $legacyTarget -notmatch 'MLLM_LAUNCH_TARGET=LEGACY'){throw "Launcher did not select Legacy: $legacyTarget"}
    }finally{
        if($null -eq $oldLauncherTest){Remove-Item Env:MLLM_LAUNCHER_TEST -ErrorAction SilentlyContinue}else{$env:MLLM_LAUNCHER_TEST=$oldLauncherTest}
    }

    $stateAfter=Get-FileFingerprint -Path $installerStatePath
    $pointerAfter=Get-FileFingerprint -Path $currentPointerPath
    Assert-FingerprintUnchanged -Before $stateBefore -After $stateAfter -Name 'installer_state.json'
    Assert-FingerprintUnchanged -Before $pointerBefore -After $pointerAfter -Name 'current.json'

    Write-Host "DESKTOP_PHASE_A_E2E=PASS package_sha256=$actual bootstrap=PASS desktop_smoke=PASS gui_preflight=PASS snapshots=PASS launcher=PASS installer_state_readonly=PASS"
}finally{
    if($null -ne $writer){try{$writer.Dispose()}catch{}}
    if($null -ne $reader){try{$reader.Dispose()}catch{}}
    if($null -ne $client){try{$client.Dispose()}catch{}}
    if($null -ne $backendProcess){try{if(-not $backendProcess.HasExited){$backendProcess.Kill()}}catch{}}
    Remove-Item -LiteralPath $backendOut,$backendErr -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $guiDataRoot,$dataRoot,$extractRoot,$outputRoot -Recurse -Force -ErrorAction SilentlyContinue
}
