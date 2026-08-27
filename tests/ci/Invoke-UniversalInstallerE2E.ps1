[CmdletBinding()]
param()
$ErrorActionPreference='Stop'
Set-StrictMode -Version 2

$Root=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$engineModule=Join-Path $Root 'installer\InstallerEngine.psm1'
$stateModule=Join-Path $Root 'installer\InstallerState.psm1'
$activationModule=Join-Path $Root 'installer\Activation.psm1'
if(-not(Test-Path -LiteralPath $engineModule -PathType Leaf)){throw "InstallerEngine.psm1 missing: $engineModule"}
Import-Module $stateModule -Force -ErrorAction Stop
Import-Module $activationModule -Force -ErrorAction Stop
Import-Module $engineModule -Force -ErrorAction Stop
Add-Type -AssemblyName System.IO.Compression -ErrorAction Stop
Add-Type -AssemblyName System.IO.Compression.FileSystem -ErrorAction Stop

$Base=Join-Path $env:RUNNER_TEMP ('mllm-e2e-'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $Base | Out-Null
$ProgramRoot=Join-Path $Base 'ProgramFiles\M-LLM\Workbench'
$ProgramDataRoot=Join-Path $Base 'ProgramData\M-LLM'
$VersionsRoot=Join-Path $ProgramRoot 'versions'
$CurrentPointer=Join-Path $ProgramDataRoot 'Workbench\current.json'
$CacheRoot=Join-Path $ProgramDataRoot 'Installer\cache'
$SharedDataRoot=Join-Path $ProgramDataRoot 'Data'

function New-E2EPaths {
    param([string]$RunId,[string]$VersionId)
    $runRoot=Join-Path $ProgramDataRoot ('Installer\runs\'+$RunId)
    [pscustomobject]@{
        ProgramRoot=$ProgramRoot
        VersionsRoot=$VersionsRoot
        InstallVersionRoot=(Join-Path $VersionsRoot $VersionId)
        ProgramDataRoot=$ProgramDataRoot
        CacheRoot=$CacheRoot
        StagingRoot=(Join-Path $ProgramDataRoot ('Installer\staging\'+$RunId))
        RunRoot=$runRoot
        StatePath=(Join-Path $runRoot 'installer_state.json')
        CurrentPointer=$CurrentPointer
        SharedDataRoot=$SharedDataRoot
        EvidencePreferredRoot=(Join-Path $Base ('Evidence\'+$RunId))
    }
}

function New-ValidPackageZip {
    param([string]$Name,[string]$Marker)
    $src=Join-Path $Base ($Name+'-src')
    New-Item -ItemType Directory -Force -Path $src | Out-Null
    foreach($f in @('Start_M_LLM_Workbench.ps1','Bootstrap_SafeCore.ps1','M_LLM_PHYSICAL_PREFLIGHT.ps1','M_LLM_GUI_PREFLIGHT.ps1')){
        $text="[CmdletBinding()]`r`nparam()`r`nWrite-Host '"+$Marker+"'`r`n"
        [IO.File]::WriteAllText((Join-Path $src $f),$text,(New-Object Text.UTF8Encoding($false)))
    }
    New-Item -ItemType Directory -Force -Path (Join-Path $src 'payload') | Out-Null
    [IO.File]::WriteAllText((Join-Path $src 'payload\marker.txt'),$Marker,(New-Object Text.UTF8Encoding($false)))
    $zip=Join-Path $Base ($Name+'.zip')
    [IO.Compression.ZipFile]::CreateFromDirectory($src,$zip)
    return [pscustomobject]@{path=$zip;sha=(Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant()}
}

function New-MissingContractZip {
    param([string]$Name)
    $src=Join-Path $Base ($Name+'-src')
    New-Item -ItemType Directory -Force -Path $src | Out-Null
    [IO.File]::WriteAllText((Join-Path $src 'Bootstrap_SafeCore.ps1'),"[CmdletBinding()]`r`nparam()`r`n",(New-Object Text.UTF8Encoding($false)))
    $zip=Join-Path $Base ($Name+'.zip')
    [IO.Compression.ZipFile]::CreateFromDirectory($src,$zip)
    return [pscustomobject]@{path=$zip;sha=(Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant()}
}

function New-TraversalZip {
    param([string]$Name)
    $zip=Join-Path $Base ($Name+'.zip')
    $fs=[IO.File]::Open($zip,[IO.FileMode]::CreateNew,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
    $archive=New-Object IO.Compression.ZipArchive($fs,[IO.Compression.ZipArchiveMode]::Create,$false)
    try{
        $entry=$archive.CreateEntry('..\escape.txt')
        $stream=$entry.Open()
        try{[byte[]]$b=[Text.Encoding]::UTF8.GetBytes('escape');$stream.Write($b,0,$b.Length)}finally{$stream.Dispose()}
    }finally{$archive.Dispose();$fs.Dispose()}
    return [pscustomobject]@{path=$zip;sha=(Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant()}
}

function New-Package {
    param([string]$Id,[string]$Version,[string]$Zip,[string]$Sha,[object[]]$Sources)
    [pscustomobject]@{id=$Id;version=$Version;file_name=($Id+'-'+$Version+'.zip');sha256=$Sha;sources=@($Sources)}
}

function New-RunState {
    param([string]$RunId,[string]$VersionId)
    $paths=New-E2EPaths -RunId $RunId -VersionId $VersionId
    foreach($dir in @($paths.RunRoot,$paths.StagingRoot,$paths.CacheRoot,$paths.EvidencePreferredRoot)){New-Item -ItemType Directory -Force -Path $dir | Out-Null}
    $state=New-MLLMInstallerState -RunId $RunId -VersionId $VersionId -Paths $paths
    Save-MLLMInstallerState -State $state -Path $paths.StatePath | Out-Null
    [pscustomobject]@{paths=$paths;state=$state}
}

function Assert-Active {
    param([string]$VersionId)
    $active=Get-MLLMActiveVersion -PointerPath $CurrentPointer
    if($null -eq $active){throw 'Active pointer is null'}
    if([string]$active.version_id -ne $VersionId){throw "Expected active $VersionId, got $($active.version_id)"}
    return $active
}

# 1. Fresh install from local package.
$v1=New-ValidPackageZip -Name 'v1' -Marker 'V1'
$r1=New-RunState -RunId 'run-v1' -VersionId 'v1'
$p1=New-Package -Id 'workbench' -Version 'v1' -Zip $v1.path -Sha $v1.sha -Sources @([pscustomobject]@{id='local-v1';kind='local_file';path=$v1.path})
$o1=Invoke-MLLMFoundationInstall -Package $p1 -Paths $r1.paths -State $r1.state -StatePath $r1.paths.StatePath -PreferredEvidenceRoot $r1.paths.EvidencePreferredRoot
if([string]$o1.status -ne 'PASS'){throw "fresh install failed: $($o1.status) $($o1.error)"}
Assert-Active -VersionId 'v1' | Out-Null
if(-not(Test-Path -LiteralPath $o1.evidence -PathType Leaf)){throw 'fresh install evidence ZIP missing'}
Write-Host 'UNIVERSAL_INSTALLER_E2E=PASS'
Write-Host 'EVIDENCE_SUCCESS=PASS'

# 2. Dead GitHub-like source followed by local fallback; lock v1 while installing v2.
$v2=New-ValidPackageZip -Name 'v2' -Marker 'V2'
$lock=[IO.File]::Open((Join-Path $ProgramRoot 'versions\v1\Start_M_LLM_Workbench.ps1'),[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
try{
    $r2=New-RunState -RunId 'run-v2' -VersionId 'v2'
    $p2=New-Package -Id 'workbench' -Version 'v2' -Zip $v2.path -Sha $v2.sha -Sources @(
        [pscustomobject]@{id='github-dead';kind='github';uri='http://127.0.0.1:9/github.zip';timeout_seconds=2;prefer_bits=$false},
        [pscustomobject]@{id='local-v2';kind='local_file';path=$v2.path}
    )
    $o2=Invoke-MLLMFoundationInstall -Package $p2 -Paths $r2.paths -State $r2.state -StatePath $r2.paths.StatePath -PreferredEvidenceRoot $r2.paths.EvidencePreferredRoot
    if([string]$o2.status -ne 'PASS'){throw "fallback install failed: $($o2.status) $($o2.error)"}
    Assert-Active -VersionId 'v2' | Out-Null
    $s2=Read-MLLMInstallerState -Path $r2.paths.StatePath
    if(@($s2.source_attempts | Where-Object {$_.source_id -eq 'github-dead' -and $_.status -eq 'FAILED'}).Count -ne 1){throw 'dead GitHub attempt not recorded'}
    if([string]$s2.selected_source -ne 'local-v2'){throw "local fallback not selected: $($s2.selected_source)"}
    if(-not(Test-Path -LiteralPath (Join-Path $ProgramRoot 'versions\v1\Start_M_LLM_Workbench.ps1') -PathType Leaf)){throw 'locked v1 was modified or removed'}
    Write-Host 'NETWORK_FAILOVER=PASS'
    Write-Host 'LOCKED_PREVIOUS_VERSION=PASS'
    Write-Host 'ATOMIC_ACTIVATION=PASS'
}finally{$lock.Dispose()}

# 3. First HTTP source fails, second HTTP source succeeds.
$v3=New-ValidPackageZip -Name 'v3' -Marker 'V3'
$probe=New-Object Net.Sockets.TcpListener([Net.IPAddress]::Loopback,0);$probe.Start();$port=([Net.IPEndPoint]$probe.LocalEndpoint).Port;$probe.Stop()
$server=Start-Job -ScriptBlock {
    param($Port,$PayloadPath)
    $listener=New-Object Net.Sockets.TcpListener([Net.IPAddress]::Loopback,[int]$Port);$listener.Start()
    try{
        $deadline=(Get-Date).AddSeconds(15);while((-not $listener.Pending()) -and (Get-Date) -lt $deadline){Start-Sleep -Milliseconds 50}
        if(-not $listener.Pending()){throw 'E2E_HTTP_ACCEPT_TIMEOUT'}
        $client=$listener.AcceptTcpClient()
        try{
            $stream=$client.GetStream();$reader=New-Object IO.StreamReader($stream,[Text.Encoding]::ASCII,$false,1024,$true)
            while($true){$line=$reader.ReadLine();if($null -eq $line -or $line -eq ''){break}}
            [byte[]]$body=[IO.File]::ReadAllBytes($PayloadPath);[byte[]]$head=[Text.Encoding]::ASCII.GetBytes("HTTP/1.1 200 OK`r`nContent-Length: $($body.Length)`r`nConnection: close`r`n`r`n")
            $stream.Write($head,0,$head.Length);$stream.Write($body,0,$body.Length);$stream.Flush()
        }finally{$client.Close()}
    }finally{$listener.Stop()}
} -ArgumentList $port,$v3.path
Start-Sleep -Milliseconds 700
try{
    $r3=New-RunState -RunId 'run-v3' -VersionId 'v3'
    $p3=New-Package -Id 'workbench' -Version 'v3' -Zip $v3.path -Sha $v3.sha -Sources @(
        [pscustomobject]@{id='http-dead';kind='http';uri='http://127.0.0.1:9/dead.zip';timeout_seconds=2;prefer_bits=$false},
        [pscustomobject]@{id='http-good';kind='http';uri=('http://127.0.0.1:'+[string]$port+'/v3.zip');timeout_seconds=5;prefer_bits=$false}
    )
    $o3=Invoke-MLLMFoundationInstall -Package $p3 -Paths $r3.paths -State $r3.state -StatePath $r3.paths.StatePath -PreferredEvidenceRoot $r3.paths.EvidencePreferredRoot
    if([string]$o3.status -ne 'PASS'){throw "HTTP failover install failed: $($o3.status) $($o3.error)"}
    Assert-Active -VersionId 'v3' | Out-Null
    $s3=Read-MLLMInstallerState -Path $r3.paths.StatePath
    if([string]$s3.selected_source -ne 'http-good'){throw "second HTTP source not selected: $($s3.selected_source)"}
    Write-Host 'HTTP_SECOND_SOURCE=PASS'
}finally{
    if($server.State -eq 'Running'){Stop-Job -Job $server -ErrorAction SilentlyContinue}
    Receive-Job -Job $server -ErrorAction SilentlyContinue | Out-Null
    Remove-Job -Job $server -Force -ErrorAction SilentlyContinue
}

# 4. Interrupt after acquisition, resume without repeating acquisition.
$v4=New-ValidPackageZip -Name 'v4' -Marker 'V4'
$r4=New-RunState -RunId 'run-v4' -VersionId 'v4'
$p4=New-Package -Id 'workbench' -Version 'v4' -Zip $v4.path -Sha $v4.sha -Sources @([pscustomobject]@{id='local-v4';kind='local_file';path=$v4.path})
$stop=Invoke-MLLMFoundationInstall -Package $p4 -Paths $r4.paths -State $r4.state -StatePath $r4.paths.StatePath -PreferredEvidenceRoot $r4.paths.EvidencePreferredRoot -StopAfterStage 'ACQUIRE'
if([string]$stop.status -ne 'INTERRUPTED'){throw "expected INTERRUPTED, got $($stop.status)"}
$mid=Read-MLLMInstallerState -Path $r4.paths.StatePath
$attemptsBefore=@($mid.source_attempts).Count
if(-not(Test-MLLMStageComplete -State $mid -Stage 'ACQUIRE')){throw 'ACQUIRE checkpoint missing before resume'}
$resume=Invoke-MLLMFoundationInstall -Package $p4 -Paths $r4.paths -State $mid -StatePath $r4.paths.StatePath -PreferredEvidenceRoot $r4.paths.EvidencePreferredRoot
if([string]$resume.status -ne 'PASS'){throw "resume failed: $($resume.status) $($resume.error)"}
$done=Read-MLLMInstallerState -Path $r4.paths.StatePath
if(@($done.source_attempts).Count -ne $attemptsBefore){throw 'resume repeated already completed ACQUIRE stage'}
Assert-Active -VersionId 'v4' | Out-Null
Write-Host 'RESUME=PASS'

# 5. Corrupt expected hash fails and preserves active v4 with failure evidence.
$r5=New-RunState -RunId 'run-bad-hash' -VersionId 'v5'
$p5=New-Package -Id 'workbench' -Version 'v5' -Zip $v4.path -Sha ('0'*64) -Sources @([pscustomobject]@{id='bad-hash-local';kind='local_file';path=$v4.path})
$o5=Invoke-MLLMFoundationInstall -Package $p5 -Paths $r5.paths -State $r5.state -StatePath $r5.paths.StatePath -PreferredEvidenceRoot $r5.paths.EvidencePreferredRoot
if([string]$o5.status -ne 'FAIL'){throw "bad hash unexpectedly passed: $($o5.status)"}
Assert-Active -VersionId 'v4' | Out-Null
if(-not(Test-Path -LiteralPath $o5.evidence -PathType Leaf)){throw 'bad hash failure evidence missing'}
Write-Host 'EVIDENCE_FAILURE=PASS'

# 6. ZIP traversal is rejected and cannot escape staging or change active pointer.
$evil=New-TraversalZip -Name 'evil'
$re=New-RunState -RunId 'run-evil' -VersionId 'evil'
$pe=New-Package -Id 'workbench' -Version 'evil' -Zip $evil.path -Sha $evil.sha -Sources @([pscustomobject]@{id='evil-local';kind='local_file';path=$evil.path})
$oe=Invoke-MLLMFoundationInstall -Package $pe -Paths $re.paths -State $re.state -StatePath $re.paths.StatePath -PreferredEvidenceRoot $re.paths.EvidencePreferredRoot
if([string]$oe.status -ne 'FAIL'){throw 'ZIP traversal package unexpectedly passed'}
if(Test-Path -LiteralPath (Join-Path $ProgramDataRoot 'Installer\staging\escape.txt') -PathType Leaf){throw 'ZIP traversal escaped staging root'}
Assert-Active -VersionId 'v4' | Out-Null
Write-Host 'ZIP_TRAVERSAL_E2E=PASS'

# 7. Missing contract candidate fails before activation and preserves v4.
$missing=New-MissingContractZip -Name 'missing'
$rm=New-RunState -RunId 'run-missing' -VersionId 'missing'
$pm=New-Package -Id 'workbench' -Version 'missing' -Zip $missing.path -Sha $missing.sha -Sources @([pscustomobject]@{id='missing-local';kind='local_file';path=$missing.path})
$om=Invoke-MLLMFoundationInstall -Package $pm -Paths $rm.paths -State $rm.state -StatePath $rm.paths.StatePath -PreferredEvidenceRoot $rm.paths.EvidencePreferredRoot
if([string]$om.status -ne 'FAIL'){throw 'invalid stage candidate unexpectedly passed'}
Assert-Active -VersionId 'v4' | Out-Null
Write-Host 'FAILED_CANDIDATE_PRESERVES_ACTIVE=PASS'

# 8. Rollback repoints to previous verified v3 and preserves v4 files.
$rolled=Invoke-MLLMRollback -PointerPath $CurrentPointer
if([string]$rolled.version_id -ne 'v3'){throw "rollback expected v3, got $($rolled.version_id)"}
if(-not(Test-Path -LiteralPath (Join-Path $VersionsRoot 'v4') -PathType Container)){throw 'rollback deleted v4 version tree'}
Write-Host 'ROLLBACK=PASS'

$requiredMarkers=@('UNIVERSAL_INSTALLER_E2E','NETWORK_FAILOVER','LOCKED_PREVIOUS_VERSION','RESUME','ATOMIC_ACTIVATION','ROLLBACK','EVIDENCE_SUCCESS','EVIDENCE_FAILURE')
Write-Host ('E2E_REQUIRED_MARKERS=PASS count='+$requiredMarkers.Count)
