#Requires -Version 7.0
# No listeners, HTTP requests or process termination: all OS boundaries below are fake.
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '../stop_dream_web.ps1')
$dreamStopJsonReader = ${function:Get-DreamStopJson}
$dreamStopLedgerReader = ${function:Read-DreamStopRefinementLedger}

$dreamStopTestId = 'identity-' + ('a' * 24)
$dreamStopWorkspace = "/api/identity/jobs/$dreamStopTestId/refinements"

function Reset-DreamStopCase {
    $created = [DateTime]::UtcNow.AddMinutes(-5)
    $script:dreamStopCase = @{
        Stops = 0; Probes = 0; Pins = 0; Stopped = $false; Disposed = $false; Mutate = $null; HttpFailure = $false
        ProcessReads = 0; TransientDiagnostic = $false
        Listeners = @([pscustomobject]@{ LocalAddress = '127.0.0.1'; LocalPort = 8766; OwningProcess = 41001 })
        Processes = @(
            [pscustomobject]@{ ProcessId = 41001; ParentProcessId = 41000; CreationDate = $created
                ExecutablePath = 'C:\Python\python.exe'
                CommandLine = '"C:\Python\python.exe" -m uvicorn app:app --host 127.0.0.1 --port 8766' },
            [pscustomobject]@{ ProcessId = 41000; ParentProcessId = 9; CreationDate = $created.AddSeconds(-1)
                ExecutablePath = 'C:\Program Files\PowerShell\7\pwsh.exe'
                CommandLine = ('"C:\Program Files\PowerShell\7\pwsh.exe" -NoProfile -File "' + (Join-Path $dreamStopRepo 'scripts/run_dream_web.ps1') + '" -Port 8766') }
        )
        PinTime = $created; Ledger = @(@{ state = 'complete' }); LedgerFailure = $false; LedgerReads = 0
        Responses = @{
            '/api/health' = @{ service = 'dream-web'; ok = $true; bind_policy = 'localhost-default'; dreamRoot = [IO.Path]::GetFullPath((Join-Path $dreamStopRepo '..')) }
            '/api/operations' = @{ service = 'dream-web'; schemaVersion = 1; pendingWork = @{
                source = 'persisted-records'; ordinary = @{ status = 'known'; pendingCount = 0 }
                identity = @{ status = 'known'; pendingCount = 0 }; batches = @{ status = 'known'; pendingCount = 0 }
            } }
            '/api/identity/jobs' = @(@{ id = $dreamStopTestId; state = 'complete' })
            '/api/identity/batches' = @()
            '/api/identity/profiles' = @(@{ state = 'ready' })
            '/api/identity/anime-profiles' = @()
            '/api/hq/jobs' = @{ jobs = @(@{ state = 'succeeded' }) }
            $dreamStopWorkspace = @{ sourceJobId = $dreamStopTestId; versions = @(@{ state = 'complete' }) }
        }
    }
}
function Get-DreamStopListeners {
    if ($script:dreamStopCase.Stopped) { return @() }
    return $script:dreamStopCase.Listeners
}
function Get-DreamStopProcesses {
    $script:dreamStopCase.ProcessReads++
    if ($script:dreamStopCase.TransientDiagnostic -and $script:dreamStopCase.ProcessReads -gt 1) {
        return @($script:dreamStopCase.Processes | Where-Object ProcessId -NE 41002)
    }
    return $script:dreamStopCase.Processes
}
function Read-DreamStopRefinementLedger([string]$DreamRoot) {
    if ($DreamRoot -ne $script:dreamStopCase.Responses['/api/health'].dreamRoot) { throw 'Ledger root was not bound to health' }
    $script:dreamStopCase.LedgerReads++
    if ($script:dreamStopCase.LedgerFailure) { throw 'Synthetic ledger read failure' }
    Assert-DreamStopStates $script:dreamStopCase.Ledger @('complete', 'failed', 'cancelled')
    return $script:dreamStopCase.Ledger.Count
}
function Get-DreamStopJson([string]$Path) {
    if ($Path -eq '/api/health') {
        $script:dreamStopCase.Probes++
        if ($script:dreamStopCase.Mutate) { & $script:dreamStopCase.Mutate }
    }
    if ($script:dreamStopCase.HttpFailure) { throw 'Synthetic HTTP failure' }
    if (-not $script:dreamStopCase.Responses.ContainsKey($Path)) { throw "Unexpected route $Path" }
    return ,$script:dreamStopCase.Responses[$Path]
}
function Open-DreamStopProcess([int]$ProcessId) {
    if ($ProcessId -ne 41001) { throw 'Wrong process pinned' }
    $script:dreamStopCase.Pins++
    $pinned = [pscustomobject]@{ Id = $ProcessId; HasExited = $false; StartTime = $script:dreamStopCase.PinTime }
    $pinned | Add-Member ScriptMethod Dispose { $script:dreamStopCase.Disposed = $true }
    return $pinned
}
function Stop-DreamStopProcess($Process) {
    if ($Process.Id -ne 41001 -or $script:dreamStopCase.Probes -ne 2 -or $script:dreamStopCase.LedgerReads -ne 2) { throw 'Stop skipped verification or selected another process' }
    $script:dreamStopCase.Stops++
    $script:dreamStopCase.Stopped = $true
}

$cases = @(
    @{ Name = 'idle exact owner stops once'; Stops = 1; Setup = {} },
    @{ Name = 'check-only never stops'; Stops = 0; CheckOnly = $true; Setup = {} },
    @{ Name = 'no listener is harmless'; Stops = 0; Setup = { $script:dreamStopCase.Listeners = @() } },
    @{ Name = 'active ordinary generation'; Refuse = $true; Setup = { $script:dreamStopCase.Responses['/api/operations'].pendingWork.ordinary.pendingCount = 1 } },
    @{ Name = 'active identity'; Refuse = $true; Setup = { $script:dreamStopCase.Responses['/api/identity/jobs'][0].state = 'sampling' } },
    @{ Name = 'active batch'; Refuse = $true; Setup = { $script:dreamStopCase.Responses['/api/identity/batches'] = @(@{ state = 'queued' }) } },
    @{ Name = 'active profile'; Refuse = $true; Setup = { $script:dreamStopCase.Responses['/api/identity/profiles'][0].state = 'preparing' } },
    @{ Name = 'active anime profile'; Refuse = $true; Setup = { $script:dreamStopCase.Responses['/api/identity/anime-profiles'] = @(@{ state = 'preparing' }) } },
    @{ Name = 'active refinement'; Refuse = $true; Setup = { $script:dreamStopCase.Ledger = @(@{ state = 'running' }) } },
    @{ Name = 'active derived HQ repair'; Refuse = $true; Setup = { $script:dreamStopCase.Responses['/api/hq/jobs'].jobs = @(@{ state = 'succeeded'; bodyRepair = @{state='running'} }) } },
    @{ Name = 'pending HQ cancellation'; Refuse = $true; Setup = { $script:dreamStopCase.Responses['/api/hq/jobs'].jobs = @(@{ state = 'running'; cancellationRequested = $true }) } },
    @{ Name = 'unknown operations count'; Refuse = $true; Setup = { $script:dreamStopCase.Responses['/api/operations'].pendingWork.ordinary.status = 'unknown' } },
    @{ Name = 'missing HQ list'; Refuse = $true; Setup = { $script:dreamStopCase.Responses['/api/hq/jobs'] = @{} } },
    @{ Name = 'malformed identity response'; Refuse = $true; Setup = { $script:dreamStopCase.Responses['/api/identity/jobs'] = 'invalid' } },
    @{ Name = 'HTTP error'; Refuse = $true; Setup = { $script:dreamStopCase.HttpFailure = $true } },
    @{ Name = 'foreign health'; Refuse = $true; Setup = { $script:dreamStopCase.Responses['/api/health'].service = 'other-app' } },
    @{ Name = 'foreign data root'; Refuse = $true; Setup = { $script:dreamStopCase.Responses['/api/health'].dreamRoot = 'E:/OtherDream' } },
    @{ Name = 'unrelated python'; Refuse = $true; Setup = { $script:dreamStopCase.Processes[0].CommandLine = 'python.exe other.py' } },
    @{ Name = 'other repo launcher'; Refuse = $true; Setup = { $script:dreamStopCase.Processes[1].CommandLine = 'pwsh.exe -NoProfile -File E:/Other/scripts/run_dream_web.ps1 -Port 8766' } },
    @{ Name = 'unproven manual launch'; Refuse = $true; Setup = { $script:dreamStopCase.Processes = @($script:dreamStopCase.Processes[0]) } },
    @{ Name = 'multiple listener owners'; Refuse = $true; Setup = { $script:dreamStopCase.Listeners += [pscustomobject]@{ LocalAddress = '::1'; LocalPort = 8766; OwningProcess = 99 } } },
    @{ Name = 'nonloopback listener'; Refuse = $true; Setup = { $script:dreamStopCase.Listeners[0].LocalAddress = '0.0.0.0' } },
    @{ Name = 'owned child still exists'; Refuse = $true; Setup = { $script:dreamStopCase.Processes += [pscustomobject]@{ ProcessId = 41002; ParentProcessId = 41001; CreationDate = [DateTime]::UtcNow } } },
    @{ Name = 'diagnostic must exit before stop'; Stops = 1; Setup = { $script:dreamStopCase.TransientDiagnostic = $true; $script:dreamStopCase.Processes += [pscustomobject]@{ ProcessId = 41002; ParentProcessId = 41001; Name = 'nvidia-smi.exe'; CreationDate = [DateTime]::UtcNow } } },
    @{ Name = 'persistent diagnostic still refuses'; Refuse = $true; Setup = { $script:dreamStopCase.Processes += [pscustomobject]@{ ProcessId = 41002; ParentProcessId = 41001; Name = 'nvidia-smi.exe'; CreationDate = [DateTime]::UtcNow } } },
    @{ Name = 'reused PID at pin'; Refuse = $true; Setup = { $script:dreamStopCase.PinTime = [DateTime]::UtcNow } },
    @{ Name = 'new job between observations'; Refuse = $true; Setup = { $script:dreamStopCase.Mutate = { if ($script:dreamStopCase.Probes -eq 2) { $script:dreamStopCase.Responses['/api/hq/jobs'].jobs = @(@{ state = 'queued' }) } } } },
    @{ Name = 'listener replaced during checks'; Refuse = $true; Setup = { $script:dreamStopCase.Mutate = { $script:dreamStopCase.Listeners[0].OwningProcess = 999 } } },
    @{ Name = 'missing historical image uses independent ledger'; Stops = 1; Setup = { $script:dreamStopCase.Responses.Remove($dreamStopWorkspace) } },
    @{ Name = 'deleted history with queued refinement still refuses'; Refuse = $true; Setup = { $script:dreamStopCase.Responses['/api/identity/jobs'][0].historyDeleted = $true; $script:dreamStopCase.Ledger = @(@{ state = 'queued' }) } },
    @{ Name = 'unreadable ledger never implies idle'; Refuse = $true; Setup = { $script:dreamStopCase.LedgerFailure = $true } },
    @{ Name = 'refinement arrives between observations'; Refuse = $true; Setup = { $script:dreamStopCase.Mutate = { if ($script:dreamStopCase.Probes -eq 2) { $script:dreamStopCase.Ledger = @(@{ state = 'queued' }) } } } }
)

foreach ($case in $cases) {
    Reset-DreamStopCase
    & $case.Setup
    $refused = $false
    try { Invoke-DreamWebStop -CheckOnly:([bool]$case.CheckOnly) | Out-Null } catch {
        $refused = $true
        if (-not $case.Refuse) { throw "FAIL $($case.Name): $($_.Exception.Message)" }
    }
    if ($refused -ne [bool]$case.Refuse -or $script:dreamStopCase.Stops -ne [int]$case.Stops) { throw "FAIL $($case.Name): wrong refusal/stop count" }
    if ($script:dreamStopCase.Pins -and -not $script:dreamStopCase.Disposed) { throw "FAIL $($case.Name): leaked process pin" }
}

# Exercise the actual HTTP/JSON error boundary too; replace only the transport.
function Invoke-WebRequest {
    param([uri]$Uri, [switch]$NoProxy, [int]$TimeoutSec, [int]$MaximumRedirection, [switch]$SkipHttpErrorCheck)
    if ($Uri.AbsoluteUri -ne "http://127.0.0.1:8766$dreamStopWorkspace" -or -not $NoProxy -or
        $TimeoutSec -ne 3 -or $MaximumRedirection -ne 0 -or -not $SkipHttpErrorCheck) { throw 'HTTP defenses changed' }
    $script:dreamStopHttpCalls++
    if ($script:dreamStopHttpCase.Timeout) { throw [TimeoutException]::new('sentinel-sensitive-body') }
    if ($script:dreamStopHttpCase.Transport) { throw [IO.IOException]::new('sentinel-sensitive-body') }
    return [pscustomobject]@{ StatusCode = $script:dreamStopHttpCase.Status; Content = $script:dreamStopHttpCase.Content }
}
$httpCases = @(
    @{ Status = 200; Content = '{"ok":true}'; Valid = $true },
    @{ Status = 200; Content = '[]'; Valid = $true },
    @{ Status = 403; Content = 'sentinel-sensitive-body'; Code = 'HTTP_403' },
    @{ Status = 404; Content = 'sentinel-sensitive-body'; Code = 'HTTP_404' },
    @{ Status = 302; Content = 'sentinel-sensitive-body'; Code = 'HTTP_302' },
    @{ Status = 500; Content = 'sentinel-sensitive-body'; Code = 'HTTP_500' },
    @{ Timeout = $true; Code = 'REQUEST_TIMEOUT_3S' },
    @{ Transport = $true; Code = 'TRANSPORT_ERROR' },
    @{ Status = 200; Content = 'sentinel-sensitive-body'; Code = 'INVALID_JSON' },
    @{ Status = 200; Content = ('x' * (16MB + 1)); Code = 'BODY_LIMIT_16M' },
    @{ Expired = $true; Code = 'TOTAL_TIMEOUT_30S' }
)
foreach ($httpCase in $httpCases) {
    $script:dreamStopHttpCase = $httpCase
    $script:dreamStopHttpCalls = 0
    $script:dreamStopDeadline = [DateTime]::UtcNow.AddSeconds($(if ($httpCase.Expired) { -1 } else { 30 }))
    $caught = $null
    try { & $dreamStopJsonReader $dreamStopWorkspace | Out-Null } catch { $caught = $_.Exception }
    if ($httpCase.Valid) {
        if ($caught) { throw "Valid HTTP/JSON response rejected: $caught" }
    } elseif (-not $caught -or $caught.Data['code'] -ne $httpCase.Code -or $caught.Data['path'] -ne $dreamStopWorkspace -or
              -not $caught.Message.Contains($dreamStopWorkspace) -or $caught.Message.Contains('sentinel-sensitive-body')) {
        throw "HTTP diagnostic case failed: $($httpCase.Code); $caught"
    }
    if ($script:dreamStopHttpCalls -ne $(if ($httpCase.Expired) { 0 } else { 1 })) { throw 'Unexpected HTTP retries or expired-deadline request' }
}

# Real bounded ledger reads use isolated fixture roots, never the live Dream data.
$fixtureBase = if (Test-Path -LiteralPath 'E:/Dream/test-runs') { 'E:/Dream/test-runs' } else { [IO.Path]::GetTempPath() }
$fixtureRoot = Join-Path $fixtureBase ('dream-stop-ledger-' + [Guid]::NewGuid().ToString('N'))
$ledgerCases = @(
    @{ Name = 'missing ledger with readable parent'; NoLedger = $true; Count = 0 },
    @{ Name = 'empty ledger'; Empty = $true; Count = 0 },
    @{ Name = 'complete without source PNG'; State = 'complete'; Count = 1 },
    @{ Name = 'failed'; State = 'failed'; Count = 1 },
    @{ Name = 'cancelled'; State = 'cancelled'; Count = 1 },
    @{ Name = 'queued without source PNG'; State = 'queued'; Refuse = $true },
    @{ Name = 'running without source PNG'; State = 'running'; Refuse = $true },
    @{ Name = 'unknown state'; State = 'unknown'; Refuse = $true },
    @{ Name = 'corrupt JSON'; Corrupt = $true; Refuse = $true },
    @{ Name = 'wrong record id'; WrongId = $true; Refuse = $true },
    @{ Name = 'wrong source id'; WrongSource = $true; Refuse = $true },
    @{ Name = 'wrong settings source'; WrongSettings = $true; Refuse = $true },
    @{ Name = 'unknown JSON filename'; ExtraJson = $true; Refuse = $true },
    @{ Name = 'oversized record'; Oversized = $true; Refuse = $true },
    @{ Name = 'junction rejected'; Junction = $true; Refuse = $true },
    @{ Name = 'selection and image are not task ledgers'; Selection = $true; Count = 1 }
)
$fixtureIndex = 0
foreach ($ledgerCase in $ledgerCases) {
    $dataRoot = Join-Path $fixtureRoot ([string]$fixtureIndex++)
    $identity = Join-Path $dataRoot 'data/identity'
    $ledger = Join-Path $identity 'refinements'
    New-Item -ItemType Directory -Path $identity -Force | Out-Null
    if (-not $ledgerCase.NoLedger) {
        New-Item -ItemType Directory -Path $ledger | Out-Null
        if (-not $ledgerCase.Empty) {
            $source = Join-Path $ledger $dreamStopTestId
            New-Item -ItemType Directory -Path $source | Out-Null
            $version = 'refine-' + ('a' * 24) + '-' + ('b' * 24)
            $recordPath = Join-Path $source ($version + '.json')
            $row = @{ id = $version; sourceJobId = $dreamStopTestId; settings = @{ sourceJobId = $dreamStopTestId }
                state = $(if ($ledgerCase.State) { $ledgerCase.State } else { 'complete' }) }
            if ($ledgerCase.WrongId) { $row.id = 'other' }
            if ($ledgerCase.WrongSource) { $row.sourceJobId = 'identity-' + ('c' * 24) }
            if ($ledgerCase.WrongSettings) { $row.settings.sourceJobId = 'identity-' + ('c' * 24) }
            $body = ConvertTo-Json -InputObject $row -Depth 5 -Compress
            if ($ledgerCase.Corrupt) { $body = '{invalid' }
            if ($ledgerCase.Oversized) { $body = 'x' * (2MB + 1) }
            [IO.File]::WriteAllText($recordPath, $body)
            if ($ledgerCase.ExtraJson) { [IO.File]::WriteAllText((Join-Path $source 'unknown.json'), '{}') }
            if ($ledgerCase.Selection) {
                [IO.File]::WriteAllText((Join-Path $source 'selection.json'), '{"versionId":"result"}')
                [IO.File]::WriteAllBytes((Join-Path $source ($version + '.png')), [byte[]]@(1,2,3))
            }
            if ($ledgerCase.Junction) {
                $target = Join-Path $dataRoot 'fixture-target'
                New-Item -ItemType Directory -Path $target | Out-Null
                New-Item -ItemType Junction -Path (Join-Path $ledger ('identity-' + ('d' * 24))) -Target $target | Out-Null
            }
        }
    }
    $script:dreamStopDeadline = [DateTime]::UtcNow.AddSeconds(30)
    $caught = $null; $count = $null
    try { $count = & $dreamStopLedgerReader $dataRoot } catch { $caught = $_.Exception }
    if ($ledgerCase.Refuse) {
        if (-not $caught) { throw "Ledger should refuse: $($ledgerCase.Name)" }
    } elseif ($caught -or $count -ne $ledgerCase.Count) { throw "Ledger case failed: $($ledgerCase.Name); $caught" }
}
Write-Output "PASS: $($cases.Count + $httpCases.Count + $ledgerCases.Count) stop/HTTP/isolated-ledger checks; no real HTTP, process inspection or termination."
