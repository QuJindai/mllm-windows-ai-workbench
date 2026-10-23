#Requires -Version 7.0
[CmdletBinding()]
param(
    [ValidateRange(1, 65535)]
    [int]$Port = 8766,
    [switch]$Json
)

# Read-only loopback probes. Never dump response bodies, commands, paths or errors.
$ErrorActionPreference = 'Stop'
$report = [ordered]@{
    schemaVersion = 1
    port = $Port
    status = 'unknown'
    diskStatus = 'unknown'
    freeBytes = $null
    checks = @()
    message = ''
}
$listenerKnown = $false
$listener = $null
try {
    # An empty result means no listener; a failed query stays unknown.
    $listener = @(Get-NetTCPConnection -State Listen -ErrorAction Stop) |
        Where-Object { $_.LocalPort -eq $Port } | Select-Object -First 1
    $listenerKnown = $true
} catch { }

try {
    $response = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/api/health" -NoProxy -UseBasicParsing -TimeoutSec 3 -MaximumRedirection 0
    $health = $response.Content | ConvertFrom-Json
    if ($health.service -ne 'dream-web') {
        $report.status = 'port-conflict'
    } elseif ($response.StatusCode -ne 200 -or $health.ok -ne $true) {
        $report.status = 'health-failed'
    } else {
        $report.status = 'ready'
    }
} catch {
    $report.status = if ($listener) { 'health-failed' } elseif ($listenerKnown) { 'not-running' } else { 'unknown' }
}

if ($report.status -eq 'ready') {
    try {
        $response = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/api/operations" -NoProxy -UseBasicParsing -TimeoutSec 3 -MaximumRedirection 0
        $ops = $response.Content | ConvertFrom-Json
        if ($response.StatusCode -ne 200 -or $ops.service -ne 'dream-web' -or $ops.schemaVersion -ne 1) {
            throw 'Invalid diagnostic response'
        }
        if ($ops.disk.status -in @('ok', 'warning', 'blocked', 'unknown')) {
            $report.diskStatus = $ops.disk.status
            if ($report.diskStatus -ne 'unknown' -and ($ops.disk.freeBytes -is [long] -or $ops.disk.freeBytes -is [int]) -and $ops.disk.freeBytes -ge 0) {
                $report.freeBytes = $ops.disk.freeBytes
            } elseif ($report.diskStatus -ne 'unknown') {
                $report.diskStatus = 'unknown'
            }
        }
        foreach ($check in $ops.checks) {
            if ($check.id -in @('frontend', 'assets', 'core', 'engine', 'wrapper', 'registry', 'dependencies') -and $check.status -in @('ok', 'missing', 'unknown')) {
                $report.checks += @{ id = $check.id; status = $check.status }
            }
        }
    } catch {
        $report.status = 'diagnostics-unavailable'
    }
}

$messages = @{
    'ready' = 'Dream 服务可访问。磁盘低于 10 GiB 提示，低于 2 GiB 阻止新生成；请核对检查项。'
    'not-running' = '未发现该端口监听，服务健康检查失败。请核对本地启动配置、前端构建及 Web 依赖。'
    'port-conflict' = '端口响应不属于 Dream。请先确认占用进程归属，再手动选择端口或处理占用。'
    'health-failed' = '端口存在监听但 Dream 健康检查失败。请核对进程归属、依赖及本地日志。'
    'diagnostics-unavailable' = 'Dream 健康检查通过，但运维诊断不可用。请核对当前服务版本。'
    'unknown' = '无法确认端口及服务状态，请核对系统权限与本地连接。'
}
$report.message = $messages[$report.status]
if ($Json) {
    $report | ConvertTo-Json -Depth 5
} else {
    Write-Output "Dream 运维诊断（只读）: $($report.message)"
    Write-Output "端口: $Port；服务: $($report.status)；磁盘: $($report.diskStatus)"
    if ($null -ne $report.freeBytes) { Write-Output ("可用空间: {0:N2} GiB" -f ($report.freeBytes / 1GB)) }
    foreach ($check in $report.checks) { Write-Output "$($check.id): $($check.status)" }
    Write-Output '未删除文件、启动服务或终止任何进程。'
}
