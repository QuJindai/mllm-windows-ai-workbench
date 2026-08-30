Set-StrictMode -Version 2
$ErrorActionPreference='Stop'

$script:ComponentEngineReady=$false
$script:AllowedPresets=@('Core','Local AI Fast','Web Workbench','Developer Tools','Full Setup')
$script:AllowedTasks=@('git','git-lfs','python','modelscope','llama-cpp','qwen35-4b','local-api','web-workbench')
$script:AllowedNetworkModes=@('AUTO_CN_FIRST','CHINA_ONLY','GLOBAL_FIRST','OFFLINE_CACHE')

function Initialize-MLLMWorkbenchComponentEngine {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)][string]$ProjectRoot,
        [Parameter(Mandatory=$true)][string]$DataRoot
    )
    if($script:ComponentEngineReady){return}
    foreach($name in @('Core','State','Detection','Network','Download','Security','Evidence','Runtime')){
        $module=Join-Path $ProjectRoot ('engine\'+$name+'.psm1')
        if(-not(Test-Path -LiteralPath $module -PathType Leaf)){throw ('COMPONENT_ENGINE_MISSING|'+$module)}
        Import-Module $module -Global -Force -ErrorAction Stop
    }
    Initialize-MLLMStateStore -Root $DataRoot | Out-Null
    Import-MLLMTasks -ProjectRoot $ProjectRoot
    $script:ComponentEngineReady=$true
}

function Assert-MLLMWorkbenchComponentPreset {
    param([Parameter(Mandatory=$true)][string]$Preset)
    if($Preset -notin $script:AllowedPresets){throw ('COMPONENT_PRESET_NOT_ALLOWED|'+$Preset)}
    return $Preset
}

function Assert-MLLMWorkbenchComponentTask {
    param([Parameter(Mandatory=$true)][string]$TaskId)
    if($TaskId -notin $script:AllowedTasks){throw ('COMPONENT_TASK_NOT_ALLOWED|'+$TaskId)}
    return $TaskId
}

function Assert-MLLMWorkbenchInstallNetworkMode {
    param([Parameter(Mandatory=$true)][string]$NetworkMode)
    if($NetworkMode -notin $script:AllowedNetworkModes){throw ('COMPONENT_NETWORK_MODE_NOT_ALLOWED|'+$NetworkMode)}
    return $NetworkMode
}

function Add-MLLMWorkbenchComponentItems {
    param(
        [Parameter(Mandatory=$true)]$Value,
        [Parameter(Mandatory=$true)]$Items
    )
    if($null -eq $Value){return}
    $idProperty=$Value.PSObject.Properties['id']
    if($null -eq $idProperty -and $Value -is [Collections.IEnumerable] -and -not($Value -is [string]) -and -not($Value -is [Collections.IDictionary])){
        foreach($nested in $Value){Add-MLLMWorkbenchComponentItems -Value $nested -Items $Items}
        return
    }
    $id=if($null -ne $idProperty){[string]$idProperty.Value}else{'unknown'}
    $statusProperty=$Value.PSObject.Properties['status']
    $summaryProperty=$Value.PSObject.Properties['summary']
    $status=if($null -ne $statusProperty){([string]$statusProperty.Value).ToUpperInvariant()}else{'UNKNOWN'}
    $summary=if($null -ne $summaryProperty){[string]$summaryProperty.Value}else{''}
    $Items.Add([ordered]@{id=$id;status=$status;summary=$summary}) | Out-Null
}

function Convert-MLLMWorkbenchComponentInstallResult {
    param(
        [Parameter(Mandatory=$true)]$Results,
        [string]$Preset='',
        [string]$TaskId='',
        [Parameter(Mandatory=$true)][string]$NetworkMode,
        [Parameter(Mandatory=$true)][string]$RunDirectory
    )
    $items=New-Object Collections.Generic.List[object]
    Add-MLLMWorkbenchComponentItems -Value $Results -Items $items
    $overall='PASS'
    if(@($items | Where-Object {[string]$_.status -eq 'FAILED'}).Count -gt 0){$overall='FAILED'}
    elseif(@($items | Where-Object {[string]$_.status -eq 'BLOCKED'}).Count -gt 0){$overall='BLOCKED'}
    elseif(@($items | Where-Object {[string]$_.status -notin @('PASS','RUNNING','READY_TO_INSTALL')}).Count -gt 0){$overall='BLOCKED'}

    return [ordered]@{
        preset=if($Preset){$Preset}else{$null}
        taskId=if($TaskId){$TaskId}else{$null}
        networkMode=$NetworkMode
        status=$overall
        runDirectory=$RunDirectory
        items=$items.ToArray()
    }
}

function Invoke-MLLMWorkbenchComponentPreset {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)][string]$ProjectRoot,
        [Parameter(Mandatory=$true)][string]$DataRoot,
        [Parameter(Mandatory=$true)][string]$Preset,
        [Parameter(Mandatory=$true)][string]$NetworkMode
    )
    Initialize-MLLMWorkbenchComponentEngine -ProjectRoot $ProjectRoot -DataRoot $DataRoot
    $Preset=Assert-MLLMWorkbenchComponentPreset -Preset $Preset
    $NetworkMode=Assert-MLLMWorkbenchInstallNetworkMode -NetworkMode $NetworkMode
    $runDir=Start-MLLMRunLog -Root $DataRoot
    $results=Invoke-MLLMPreset -Preset $Preset -ProjectRoot $ProjectRoot -DataRoot $DataRoot -NetworkMode $NetworkMode -RunDir $runDir
    $results | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath (Join-Path $runDir 'component-install-summary.json') -Encoding UTF8
    return Convert-MLLMWorkbenchComponentInstallResult -Results $results -Preset $Preset -NetworkMode $NetworkMode -RunDirectory $runDir
}

function Invoke-MLLMWorkbenchComponentTask {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)][string]$ProjectRoot,
        [Parameter(Mandatory=$true)][string]$DataRoot,
        [Parameter(Mandatory=$true)][string]$TaskId,
        [Parameter(Mandatory=$true)][string]$NetworkMode
    )
    Initialize-MLLMWorkbenchComponentEngine -ProjectRoot $ProjectRoot -DataRoot $DataRoot
    $TaskId=Assert-MLLMWorkbenchComponentTask -TaskId $TaskId
    $NetworkMode=Assert-MLLMWorkbenchInstallNetworkMode -NetworkMode $NetworkMode
    $runDir=Start-MLLMRunLog -Root $DataRoot
    $context=@{ProjectRoot=$ProjectRoot;DataRoot=$DataRoot;NetworkMode=$NetworkMode;RunDir=$runDir}
    $result=Invoke-MLLMTask -Id $TaskId -Action Install -Context $context
    @($result) | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath (Join-Path $runDir 'component-install-summary.json') -Encoding UTF8
    return Convert-MLLMWorkbenchComponentInstallResult -Results $result -TaskId $TaskId -NetworkMode $NetworkMode -RunDirectory $runDir
}

Export-ModuleMember -Function Initialize-MLLMWorkbenchComponentEngine,Invoke-MLLMWorkbenchComponentPreset,Invoke-MLLMWorkbenchComponentTask
