#Requires -Version 7.0
<#
.SYNOPSIS
Stop this repository's idle background Dream web server on 127.0.0.1:8766.
.DESCRIPTION
Close submission pages before stopping. Checks are observations, not a server
maintenance lock. Unknown ownership/state, active work or child processes refuse
termination. Cancel work in the UI and wait, or use Ctrl+C in the verified
foreground run_dream_web.ps1 window. No process-tree kill and no file deletion.
.EXAMPLE
pwsh -NoProfile -File E:/Dream/repo/scripts/stop_dream_web.ps1 -CheckOnly
.EXAMPLE
pwsh -NoProfile -File E:/Dream/repo/scripts/stop_dream_web.ps1
#>
[CmdletBinding()]
param([switch]$CheckOnly)

$ErrorActionPreference = 'Stop'
$dreamStopRepo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))

if (-not ('DreamWebStopNative' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;
public static class DreamWebStopNative {
    [DllImport("shell32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    static extern IntPtr CommandLineToArgvW(string command, out int count);
    [DllImport("kernel32.dll")] static extern IntPtr LocalFree(IntPtr value);
    [DllImport("kernel32.dll", SetLastError=true)]
    static extern bool TerminateProcess(SafeProcessHandle process, uint code);
    public static string[] Arguments(string command) {
        int count; var memory = CommandLineToArgvW(command, out count);
        if (memory == IntPtr.Zero) throw new Win32Exception();
        try {
            var result = new string[count];
            for (int i=0; i<count; i++) result[i] = Marshal.PtrToStringUni(Marshal.ReadIntPtr(memory, i*IntPtr.Size));
            return result;
        } finally { LocalFree(memory); }
    }
    public static void Stop(SafeProcessHandle process) {
        if (!TerminateProcess(process, 0)) throw new Win32Exception();
    }
}
'@
}

function Get-DreamStopListeners {
    return @(Get-NetTCPConnection -State Listen -ErrorAction Stop | Where-Object LocalPort -EQ 8766)
}
function Get-DreamStopProcesses { return @(Get-CimInstance Win32_Process -ErrorAction Stop) }
function New-DreamStopCheckError([string]$Path, [string]$Code, [int]$ElapsedMs, [int]$HttpStatus = 0) {
    # Report only our route, timing and status classification; never response
    # bodies, exception messages, command lines, credentials or image metadata.
    $hint = switch ($Code) {
        'HTTP_404' { '接口或对应历史资源不可用，不能将此响应当作没有活动任务。' }
        'HTTP_403' { '本机接口拒绝访问，未能读取任务状态。' }
        default { '未能完整确认任务状态。' }
    }
    $errorRecord = [InvalidOperationException]::new("Dream 停止检查失败 [$Code] GET $Path (${ElapsedMs}ms)；$hint 拒绝停止。请检查接口或历史资源状态，或在已确认的前台窗口按 Ctrl+C。")
    $errorRecord.Data['path'] = $Path
    $errorRecord.Data['code'] = $Code
    $errorRecord.Data['elapsedMs'] = $ElapsedMs
    if ($HttpStatus) { $errorRecord.Data['httpStatus'] = $HttpStatus }
    return $errorRecord
}
function Get-DreamStopJson([string]$Path) {
    $timer = [Diagnostics.Stopwatch]::StartNew()
    if ([DateTime]::UtcNow -gt $script:dreamStopDeadline) { throw (New-DreamStopCheckError $Path 'TOTAL_TIMEOUT_30S' 0) }
    try {
        $response = Invoke-WebRequest -Uri "http://127.0.0.1:8766$Path" -NoProxy -TimeoutSec 3 -MaximumRedirection 0 -SkipHttpErrorCheck
    } catch {
        $httpStatus = 0
        if ($_.Exception.Response -and $_.Exception.Response.StatusCode) { $httpStatus = [int]$_.Exception.Response.StatusCode }
        $problem = $_.Exception
        $timedOut = $false
        for ($depth = 0; $problem -and $depth -lt 8; $depth++) {
            if ($problem -is [TimeoutException] -or $problem -is [OperationCanceledException]) { $timedOut = $true }
            $problem = $problem.InnerException
        }
        $code = if ($httpStatus) { "HTTP_$httpStatus" } elseif ($timedOut) { 'REQUEST_TIMEOUT_3S' } else { 'TRANSPORT_ERROR' }
        throw (New-DreamStopCheckError $Path $code $timer.ElapsedMilliseconds $httpStatus)
    }
    if ($response.StatusCode -ne 200) {
        throw (New-DreamStopCheckError $Path "HTTP_$($response.StatusCode)" $timer.ElapsedMilliseconds ([int]$response.StatusCode))
    }
    if ($response.Content.Length -gt 16MB) { throw (New-DreamStopCheckError $Path 'BODY_LIMIT_16M' $timer.ElapsedMilliseconds) }
    try {
        $value = ConvertFrom-Json -InputObject $response.Content -AsHashtable -NoEnumerate -ErrorAction Stop
        return ,$value
    } catch { throw (New-DreamStopCheckError $Path 'INVALID_JSON' $timer.ElapsedMilliseconds) }
}
function Open-DreamStopProcess([int]$ProcessId) {
    $process = [Diagnostics.Process]::GetProcessById($ProcessId)
    $null = $process.SafeHandle # Pin the process object; never terminate a later reused PID.
    return $process
}
function Stop-DreamStopProcess($Process) {
    [DreamWebStopNative]::Stop($Process.SafeHandle)
    if (-not $Process.WaitForExit(10000)) { throw '已请求停止，但尚未确认该进程退出；不处理其他进程。' }
}
function Assert-DreamStopOwner($Listeners, $Rows, [int]$DiagnosticWait = 0) {
    $owners = @($Listeners.OwningProcess | Select-Object -Unique)
    if ($owners.Count -ne 1 -or @($Listeners | Where-Object LocalAddress -NotIn @('127.0.0.1', '::1')).Count) {
        throw '8766 的监听归属或回环绑定不明确；拒绝停止。'
    }
    $owner = @($Rows | Where-Object ProcessId -EQ $owners[0])
    if ($owner.Count -ne 1 -or -not $owner[0].CommandLine -or -not $owner[0].CreationDate) { throw '无法确认监听进程；拒绝停止。' }
    $owner = $owner[0]
    $arguments = [DreamWebStopNative]::Arguments($owner.CommandLine)
    if ([IO.Path]::GetFileName($owner.ExecutablePath) -notmatch '^python(?:w)?\.exe$' -or
        $arguments.Count -ne 8 -or ($arguments[1..7] -join '|') -cne '-m|uvicorn|app:app|--host|127.0.0.1|--port|8766') {
        throw '监听进程不是预期的 Dream uvicorn 命令；拒绝停止。'
    }
    # The module name alone does not prove which repo app.py was imported.
    # Require the exact launcher path in a live, older ancestor (venv shim allowed).
    $ancestor = $owner
    $proven = $false
    for ($depth = 0; $depth -lt 4; $depth++) {
        $parent = @($Rows | Where-Object ProcessId -EQ $ancestor.ParentProcessId)
        if ($parent.Count -ne 1 -or -not $parent[0].CommandLine -or -not $parent[0].CreationDate -or
            $parent[0].CreationDate -gt $ancestor.CreationDate) { break }
        $ancestor = $parent[0]
        $ancestorArgs = [DreamWebStopNative]::Arguments($ancestor.CommandLine)
        if ([IO.Path]::GetFileName($ancestor.ExecutablePath) -ieq 'pwsh.exe') {
            if ($ancestorArgs.Count -eq 6 -and $ancestorArgs[1] -ieq '-NoProfile' -and $ancestorArgs[2] -ieq '-File' -and
                [IO.Path]::GetFullPath($ancestorArgs[3]) -ieq (Join-Path $dreamStopRepo 'scripts/run_dream_web.ps1') -and
                $ancestorArgs[4] -ieq '-Port' -and $ancestorArgs[5] -eq '8766') { $proven = $true }
            break
        }
        if ([IO.Path]::GetFileName($ancestor.ExecutablePath) -notmatch '^python(?:w)?\.exe$') { break }
    }
    if (-not $proven) { throw '无法证明监听来自本仓库启动脚本；拒绝停止。请在已确认的前台窗口按 Ctrl+C。' }
    $children = @($Rows | Where-Object { $_.ParentProcessId -eq $owner.ProcessId -and $_.CreationDate -ge $owner.CreationDate })
    if ($children.Count) {
        # Hardware polling briefly spawns nvidia-smi. Never ignore or kill it:
        # allow two short waits, then re-prove listener/ancestry and child absence.
        if ($DiagnosticWait -lt 2 -and [DateTime]::UtcNow -lt $script:dreamStopDeadline -and
            @($children | Where-Object Name -NE 'nvidia-smi.exe').Count -eq 0) {
            Start-Sleep -Milliseconds 200
            return Assert-DreamStopOwner @(Get-DreamStopListeners) (Get-DreamStopProcesses) ($DiagnosticWait + 1)
        }
        throw 'Dream 仍有子进程；拒绝停止。先在界面取消任务并等待退出，或在已确认的前台窗口按 Ctrl+C。'
    }
    return $owner
}
function Assert-DreamStopStates($Rows, [string[]]$Terminal) {
    if ($Rows -isnot [array] -or $Rows.Count -gt 256) { throw '任务清单未知或超过安全检查上限；拒绝停止。' }
    foreach ($row in $Rows) {
        if ($row -isnot [System.Collections.IDictionary] -or $row.state -notin $Terminal) {
            throw '仍有活动任务或无法确认其终态；拒绝停止。请先在界面取消并等待任务结束。'
        }
    }
}
function Read-DreamStopRefinementLedger([string]$DreamRoot) {
    # Called only after health.dreamRoot matches the verified repo's data root.
    # submit() durably writes queued before dispatch. Inspect every source,
    # including deleted/missing images; a workspace GET requires the base PNG.
    $records = 0
    try {
        $identity = Get-Item -LiteralPath (Join-Path $DreamRoot 'data/identity') -Force -ErrorAction Stop
        if (-not $identity.PSIsContainer) { throw 'Not a directory' }
        for ($ancestor = $identity; $null -ne $ancestor; $ancestor = $ancestor.Parent) {
            if ($ancestor.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Redirected ancestor' }
        }
        # Enumerating the parent distinguishes an absent ledger from an access
        # failure. No refinement can be dispatched before its ledger exists.
        $entries = 0
        $ledger = $null
        foreach ($entry in $identity.EnumerateFileSystemInfos()) {
            if (++$entries -gt 2000) { throw 'Directory limit' }
            if ($entry.Name -ieq 'refinements') { $ledger = $entry }
        }
        if ($null -eq $ledger) { return 0 }
        if ($ledger -isnot [IO.DirectoryInfo] -or ($ledger.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Redirected ledger' }
        foreach ($source in $ledger.EnumerateFileSystemInfos()) {
            if (++$entries -gt 12000 -or [DateTime]::UtcNow -gt $script:dreamStopDeadline) { throw 'Scan limit' }
            if ($source -isnot [IO.DirectoryInfo] -or $source.Name -cnotmatch '^identity-[a-f0-9]{24}$' -or
                ($source.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Invalid source folder' }
            $sourceRecords = 0
            foreach ($file in $source.EnumerateFileSystemInfos()) {
                if (++$entries -gt 12000 -or [DateTime]::UtcNow -gt $script:dreamStopDeadline) { throw 'Scan limit' }
                if ($file -isnot [IO.FileInfo] -or ($file.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Redirected record' }
                if ($file.Extension -ine '.json' -or $file.Name -ieq 'selection.json') { continue }
                if ($file.BaseName -cnotmatch '^refine-([a-f0-9]{24})-[a-f0-9]{24}$' -or
                    $source.Name -cne ('identity-' + $Matches[1])) { throw 'Invalid record filename' }
                if (++$records -gt 2000 -or ++$sourceRecords -gt 128) { throw 'Record limit' }
                $stream = $null
                try {
                    # Allow atomic os.replace while reading a pinned old file;
                    # diagnostics must not cause Windows sharing violations.
                    $stream = [IO.File]::Open($file.FullName, [IO.FileMode]::Open, [IO.FileAccess]::Read,
                        ([IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete))
                    $buffer = [byte[]]::new(2MB + 1)
                    $count = 0
                    do {
                        $read = $stream.Read($buffer, $count, $buffer.Length - $count)
                        $count += $read
                    } while ($read -gt 0 -and $count -lt $buffer.Length)
                    if ($count -gt 2MB) { throw 'Record size limit' }
                    $text = [Text.UTF8Encoding]::new($false, $true).GetString($buffer, 0, $count).TrimStart([char]0xfeff)
                    $row = ConvertFrom-Json -InputObject $text -AsHashtable -NoEnumerate -ErrorAction Stop
                } finally { if ($stream) { $stream.Dispose() } }
                if ($row -isnot [System.Collections.IDictionary] -or $row.id -cne $file.BaseName -or
                    $row.sourceJobId -cne $source.Name -or $row.settings -isnot [System.Collections.IDictionary] -or
                    $row.settings.sourceJobId -cne $source.Name -or
                    $row.state -notin @('complete', 'failed', 'cancelled', 'queued', 'running')) { throw 'Invalid ledger binding/state' }
                if ($row.state -in @('queued', 'running')) {
                    throw [InvalidOperationException]::new("REFINEMENT_ACTIVE:$($row.id)")
                }
            }
        }
    } catch {
        if ($_.Exception.Message -match '^REFINEMENT_ACTIVE:(refine-[a-f0-9]{24}-[a-f0-9]{24})$') {
            throw "本地精修账本仍有活动任务 $($Matches[1])；拒绝停止。请先在界面取消并等待任务结束。"
        }
        throw '本地精修账本不可完整核验（路径、内容、归属、状态或扫描上限）；拒绝停止。未将缺失图片或 HTTP 404 当作空闲。'
    }
    return $records
}
function Assert-DreamStopIdle {
    $health = Get-DreamStopJson '/api/health'
    if ($health.service -cne 'dream-web' -or $health.ok -ne $true -or
        $health.bind_policy -cne 'localhost-default' -or -not $health.dreamRoot -or
        [IO.Path]::GetFullPath($health.dreamRoot) -ine [IO.Path]::GetFullPath((Join-Path $dreamStopRepo '..'))) {
        throw '健康接口与本机 Dream 不匹配；拒绝停止。'
    }
    $ops = Get-DreamStopJson '/api/operations'
    if ($ops.service -cne 'dream-web' -or $ops.schemaVersion -ne 1 -or $ops.pendingWork.source -cne 'persisted-records') {
        throw '运维状态契约不匹配；拒绝停止。'
    }
    foreach ($kind in @('ordinary', 'identity', 'batches')) {
        $pending = $ops.pendingWork[$kind]
        if ($pending.status -cne 'known' -or ($pending.pendingCount -isnot [long] -and $pending.pendingCount -isnot [int])) {
            throw '任务数量未知；拒绝停止。'
        }
        if ($pending.pendingCount -ne 0) { throw '仍有生成、人物或批次任务；拒绝停止。请先在界面取消并等待任务结束。' }
    }
    $jobs = Get-DreamStopJson '/api/identity/jobs'
    Assert-DreamStopStates $jobs @('complete', 'failed', 'cancelled')
    Assert-DreamStopStates (Get-DreamStopJson '/api/identity/batches') @('complete', 'failed', 'cancelled')
    foreach ($path in @('/api/identity/profiles', '/api/identity/anime-profiles')) {
        Assert-DreamStopStates (Get-DreamStopJson $path) @('ready', 'failed', 'archived')
    }
    $hq = Get-DreamStopJson '/api/hq/jobs'
    Assert-DreamStopStates $hq.jobs @('succeeded', 'failed', 'cancelled')
    foreach ($job in $hq.jobs) {
        if ($job['bodyRepair'] -and $job.bodyRepair.state -in @('queued', 'running')) { throw 'HQ 局部自动修整仍在等待或执行，拒绝停止。' }
    }
    $script:dreamStopRefinementRecords = Read-DreamStopRefinementLedger $health.dreamRoot
}
function Invoke-DreamWebStop([switch]$CheckOnly) {
    $script:dreamStopDeadline = [DateTime]::UtcNow.AddSeconds(30)
    $listeners = @(Get-DreamStopListeners)
    if (-not $listeners.Count) { Write-Output 'DREAM_WEB_NOT_RUNNING port=8766'; return }
    $owner = Assert-DreamStopOwner $listeners (Get-DreamStopProcesses)
    $process = Open-DreamStopProcess $owner.ProcessId
    try {
        # CIM creation timestamps have microsecond precision; the pinned handle
        # exposes 100ns ticks. Permit only that representation's rounding.
        if ($process.HasExited -or [Math]::Abs(($process.StartTime.ToUniversalTime() - $owner.CreationDate.ToUniversalTime()).Ticks) -gt 10) {
            throw '监听进程身份已改变；拒绝停止。'
        }
        for ($pass = 0; $pass -lt 2; $pass++) {
            Assert-DreamStopIdle
            $current = Assert-DreamStopOwner @(Get-DreamStopListeners) (Get-DreamStopProcesses)
            if ($current.ProcessId -ne $owner.ProcessId -or $current.CreationDate -ne $owner.CreationDate -or $process.HasExited) {
                throw '检查期间监听进程已改变；拒绝停止。'
            }
        }
        if ($CheckOnly) { Write-Output "DREAM_WEB_IDLE_VERIFIED PID=$($owner.ProcessId) port=8766 refinements=$script:dreamStopRefinementRecords (未停止)"; return }
        Stop-DreamStopProcess $process
        if (@(Get-DreamStopListeners).Count) { throw '已确认目标进程退出，但端口仍有监听；未终止新进程。' }
        Write-Output "DREAM_WEB_STOPPED PID=$($owner.ProcessId) port=8766"
    } finally { $process.Dispose() }
}

if ($MyInvocation.InvocationName -ne '.') { Invoke-DreamWebStop -CheckOnly:$CheckOnly }
