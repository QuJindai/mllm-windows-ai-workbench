[CmdletBinding()]
param()
$ErrorActionPreference='Stop'
Set-StrictMode -Version 2

$Root=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$pathsModule=Join-Path $Root 'installer\InstallerPaths.psm1'
$stateModule=Join-Path $Root 'installer\InstallerState.psm1'
$acqModule=Join-Path $Root 'installer\Acquisition.psm1'
if(-not(Test-Path -LiteralPath $acqModule -PathType Leaf)){throw "Acquisition.psm1 missing: $acqModule"}

Import-Module $pathsModule -Force -ErrorAction Stop
Import-Module $stateModule -Force -ErrorAction Stop
Import-Module $acqModule -Force -ErrorAction Stop

$fixtureRoot=Join-Path $env:RUNNER_TEMP ('mllm-acq-'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $fixtureRoot | Out-Null
$payload=Join-Path $fixtureRoot 'payload.zip'
[IO.File]::WriteAllBytes($payload,[Text.Encoding]::UTF8.GetBytes('mllm-universal-installer-acquisition-fixture'))
$sha=(Get-FileHash -LiteralPath $payload -Algorithm SHA256).Hash.ToLowerInvariant()

function New-TestState {
    param([string]$Suffix)
    $runId='ci-acq-'+$Suffix+'-'+([guid]::NewGuid().ToString('N').Substring(0,8))
    $versionId='ci-v1'
    $paths=Get-MLLMInstallerPaths -RunId $runId -VersionId $versionId
    $state=New-MLLMInstallerState -RunId $runId -VersionId $versionId -Paths $paths
    $statePath=Join-Path $fixtureRoot ($Suffix+'-state.json')
    Save-MLLMInstallerState -State $state -Path $statePath | Out-Null
    return [pscustomobject]@{state=$state;state_path=$statePath;cache=(Join-Path $fixtureRoot ($Suffix+'-cache'))}
}

# Case 1: unreachable HTTP must fall through to a valid local file.
$c1=New-TestState -Suffix 'local'
$package1=[pscustomobject]@{
    id='safe-core-payload'
    version='ci-v1'
    file_name='safe-core-ci.zip'
    sha256=$sha
    sources=@(
        [pscustomobject]@{id='dead-http';kind='http';uri='http://127.0.0.1:9/never.zip';timeout_seconds=2},
        [pscustomobject]@{id='offline-local';kind='local_file';path=$payload}
    )
}
$r1=Invoke-MLLMAcquirePackage -Package $package1 -CacheRoot $c1.cache -State $c1.state -StatePath $c1.state_path
if([string]$r1.source_id -ne 'offline-local'){throw "failover did not select local source: $($r1.source_id)"}
if(-not(Test-Path -LiteralPath $r1.path -PathType Leaf)){throw 'acquired local file missing'}
if((Get-FileHash -LiteralPath $r1.path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $sha){throw 'acquired local file hash mismatch'}
$loaded1=Read-MLLMInstallerState -Path $c1.state_path
if(@($loaded1.source_attempts | Where-Object {$_.source_id -eq 'dead-http' -and $_.status -eq 'FAILED'}).Count -ne 1){throw 'failed HTTP source not recorded exactly once'}
if(@($loaded1.source_attempts | Where-Object {$_.source_id -eq 'offline-local' -and $_.status -eq 'PASS'}).Count -ne 1){throw 'successful local source not recorded exactly once'}
if([string]$loaded1.selected_source -ne 'offline-local'){throw 'selected_source was not persisted'}
Write-Host 'ACQUISITION_FAILOVER_SMOKE=PASS selected=offline-local'

# Case 2: unreachable HTTP must fall through to a second HTTP provider.
$probe=New-Object Net.Sockets.TcpListener([Net.IPAddress]::Loopback,0)
$probe.Start()
$port=([Net.IPEndPoint]$probe.LocalEndpoint).Port
$probe.Stop()
$server=Start-Job -ScriptBlock {
    param($Port,$PayloadPath)
    $listener=New-Object Net.Sockets.TcpListener([Net.IPAddress]::Loopback,[int]$Port)
    $listener.Start()
    try{
        $client=$listener.AcceptTcpClient()
        try{
            $stream=$client.GetStream()
            $reader=New-Object IO.StreamReader($stream,[Text.Encoding]::ASCII,$false,1024,$true)
            while($true){$line=$reader.ReadLine();if($null -eq $line -or $line -eq ''){break}}
            [byte[]]$body=[IO.File]::ReadAllBytes($PayloadPath)
            [byte[]]$head=[Text.Encoding]::ASCII.GetBytes("HTTP/1.1 200 OK`r`nContent-Length: $($body.Length)`r`nConnection: close`r`n`r`n")
            $stream.Write($head,0,$head.Length)
            $stream.Write($body,0,$body.Length)
            $stream.Flush()
        }finally{$client.Close()}
    }finally{$listener.Stop()}
} -ArgumentList $port,$payload
Start-Sleep -Milliseconds 500
try{
    $c2=New-TestState -Suffix 'http'
    $package2=[pscustomobject]@{
        id='safe-core-payload-http'
        version='ci-v1'
        file_name='safe-core-http-ci.zip'
        sha256=$sha
        sources=@(
            [pscustomobject]@{id='dead-http-2';kind='http';uri='http://127.0.0.1:9/never-again.zip';timeout_seconds=2},
            [pscustomobject]@{id='http-good';kind='http';uri=('http://127.0.0.1:'+[string]$port+'/payload.zip');timeout_seconds=5;prefer_bits=$false}
        )
    }
    $r2=Invoke-MLLMAcquirePackage -Package $package2 -CacheRoot $c2.cache -State $c2.state -StatePath $c2.state_path
    if([string]$r2.source_id -ne 'http-good'){throw "HTTP failover selected wrong source: $($r2.source_id)"}
    if((Get-FileHash -LiteralPath $r2.path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $sha){throw 'HTTP acquired file hash mismatch'}
    $loaded2=Read-MLLMInstallerState -Path $c2.state_path
    if(@($loaded2.source_attempts | Where-Object {$_.source_id -eq 'dead-http-2' -and $_.status -eq 'FAILED'}).Count -ne 1){throw 'failed first HTTP source not recorded'}
    if(@($loaded2.source_attempts | Where-Object {$_.source_id -eq 'http-good' -and $_.status -eq 'PASS'}).Count -ne 1){throw 'successful HTTP source not recorded'}
    Write-Host 'ACQUISITION_HTTP_FAILOVER_SMOKE=PASS selected=http-good'
}finally{
    if($server.State -eq 'Running'){Stop-Job -Job $server -ErrorAction SilentlyContinue}
    Receive-Job -Job $server -ErrorAction SilentlyContinue | Out-Null
    Remove-Job -Job $server -Force -ErrorAction SilentlyContinue
}
