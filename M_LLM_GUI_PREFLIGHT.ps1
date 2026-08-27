[CmdletBinding()]
param(
    [string]$DataRoot='',
    [ValidateSet('AUTO_CN_FIRST','CHINA_ONLY','GLOBAL_FIRST','OFFLINE_CACHE','CUSTOM_PROXY')][string]$NetworkMode='OFFLINE_CACHE'
)

$ErrorActionPreference='Stop'
Set-StrictMode -Version 2
$ProjectRoot=$PSScriptRoot

if(-not $DataRoot){
    $downloadRoot=Join-Path $env:USERPROFILE 'Downloads'
    if(-not(Test-Path -LiteralPath $downloadRoot -PathType Container)){$downloadRoot=$env:TEMP}
    $DataRoot=Join-Path $downloadRoot 'M_LLM_GUI_PREFLIGHT'
}
$DataRoot=[System.IO.Path]::GetFullPath($DataRoot)
New-Item -ItemType Directory -Force -Path $DataRoot | Out-Null
$ReportPath=Join-Path $DataRoot 'gui_preflight.json'
$StartedAt=Get-Date

$report=[ordered]@{
    schema='mllm.gui-preflight.v1'
    mode='NON_INSTALLING'
    status='RUNNING'
    network_mode=$NetworkMode
    core_install_authorized=$false
    install_actions_executed=0
    network_actions_executed=0
    started_at=$StartedAt.ToString('o')
    finished_at=$null
    duration_seconds=0
    project_root=$ProjectRoot
    data_root=$DataRoot
    task_count=0
    snapshot_errors=0
    tasks=@()
    errors=@()
}

function Save-GuiPreflightReport {
    param([System.Collections.IDictionary]$Report)
    $Report.finished_at=(Get-Date).ToString('o')
    $Report.duration_seconds=[Math]::Round(((Get-Date)-$StartedAt).TotalSeconds,3)
    $Report | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $ReportPath -Encoding UTF8
}

try{
    $bootstrap=Join-Path $ProjectRoot 'Bootstrap_SafeCore.ps1'
    if(-not(Test-Path -LiteralPath $bootstrap -PathType Leaf)){throw 'Bootstrap_SafeCore.ps1 missing'}
    & $bootstrap -ProjectRoot $ProjectRoot | Out-Host

    $adapter=Join-Path $ProjectRoot 'gui\GuiAdapter.psm1'
    if(-not(Test-Path -LiteralPath $adapter -PathType Leaf)){throw 'gui\GuiAdapter.psm1 missing after bootstrap'}
    Import-Module $adapter -Force -ErrorAction Stop

    $snapshot=Get-MLLMGuiSnapshot -ProjectRoot $ProjectRoot -DataRoot $DataRoot -NetworkMode $NetworkMode
    if($null -eq $snapshot){throw 'GUI snapshot returned null'}

    $snapshotErrors=@($snapshot.snapshot_errors)
    $taskRows=@($snapshot.tasks)
    $report.snapshot_errors=$snapshotErrors.Count
    $report.task_count=$taskRows.Count
    $report.tasks=@($taskRows | ForEach-Object {
        [pscustomobject]@{
            id=[string]$_.id
            status=[string]$_.status
            summary=[string]$_.summary
            repair_available=[bool]$_.repair_available
            repair_task=[string]$_.repair_task
        }
    })

    if([string]$snapshot.network_mode -ne $NetworkMode){
        throw "GUI snapshot network mode mismatch requested=$NetworkMode actual=$($snapshot.network_mode)"
    }
    if($snapshotErrors.Count -gt 0){
        $detail=($snapshotErrors | ForEach-Object { '['+[string]$_.scope+':'+[string]$_.id+'] '+[string]$_.error }) -join ' | '
        throw "GUI snapshot contains internal errors: $detail"
    }

    # Keep the source ASCII-only because Windows PowerShell 5.1 parses raw
    # GitHub UTF-8 files without BOM using the active Windows ANSI code page.
    # The final regex branch still matches the Chinese CommandNotFound text.
    $commandScopePattern='CommandNotFoundException|not recognized as the name of a cmdlet|\u65E0\u6CD5\u5C06.+\u8BC6\u522B\u4E3A'
    $badCommands=@($taskRows | Where-Object { ([string]$_.summary) -match $commandScopePattern })
    if($badCommands.Count -gt 0){
        throw ('GUI task detection lost required command scope: '+(($badCommands | ForEach-Object { [string]$_.id }) -join ','))
    }

    foreach($requiredId in @('llama-cpp','local-api','modelscope','python','qwen35-4b','web-workbench')){
        if(-not(@($taskRows | Where-Object { [string]$_.id -eq $requiredId }).Count)){
            throw "GUI snapshot missing required task row: $requiredId"
        }
    }

    $report.status='PASS'
    Save-GuiPreflightReport -Report $report
    Write-Host "GUI_PREFLIGHT=PASS tasks=$($report.task_count) snapshot_errors=0 network_mode=$NetworkMode core_install_authorized=false report=$ReportPath"
    exit 0
}catch{
    $report.status='FAIL'
    $report.errors=@([string]$_.Exception.ToString())
    try{Save-GuiPreflightReport -Report $report}catch{}
    Write-Host "GUI_PREFLIGHT=FAIL network_mode=$NetworkMode core_install_authorized=false report=$ReportPath"
    Write-Error $_.Exception.ToString()
    exit 2
}
