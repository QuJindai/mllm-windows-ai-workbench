[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$PipeName,
    [Parameter(Mandatory=$true)][string]$SessionToken,
    [Parameter(Mandatory=$true)][string]$ProtocolVersion,
    [Parameter(Mandatory=$true)][string]$ProjectRoot,
    [Parameter(Mandatory=$true)][string]$DataRoot,
    [Parameter(Mandatory=$true)][string]$NetworkMode
)

$ErrorActionPreference='Stop'
Set-StrictMode -Version 2
if($ProtocolVersion -ne '1.0'){throw 'ProtocolVersion must be 1.0'}
$script:SafeCoreReady=$false

function Test-SessionToken {
    param([string]$Actual,[string]$Expected)
    [byte[]]$a=[Text.Encoding]::UTF8.GetBytes([string]$Actual)
    [byte[]]$b=[Text.Encoding]::UTF8.GetBytes([string]$Expected)
    [int]$length=[Math]::Max($a.Length,$b.Length)
    [int]$diff=$a.Length -bxor $b.Length
    for([int]$i=0;$i -lt $length;$i++){
        [int]$av=if($i -lt $a.Length){$a[$i]}else{0}
        [int]$bv=if($i -lt $b.Length){$b[$i]}else{0}
        $diff=$diff -bor ($av -bxor $bv)
    }
    return ($diff -eq 0)
}

function Get-ObjectValue {
    param($Object,[Parameter(Mandatory=$true)][string]$Name,$Default=$null)
    if($null -eq $Object){return $Default}
    if($Object -is [Collections.IDictionary]){
        if($Object.Contains($Name)){return $Object[$Name]}
        return $Default
    }
    $property=$Object.PSObject.Properties[$Name]
    if($null -ne $property){return $property.Value}
    return $Default
}

function Initialize-SafeCore {
    if($script:SafeCoreReady){return}
    $bootstrap=Join-Path $ProjectRoot 'Bootstrap_SafeCore.ps1'
    if(-not(Test-Path -LiteralPath $bootstrap -PathType Leaf)){throw 'Bootstrap_SafeCore.ps1 missing'}
    & $bootstrap -ProjectRoot $ProjectRoot | Out-Null

    foreach($name in @('Core','State','Detection','Network','Download','Security','Evidence','Runtime')){
        $module=Join-Path $ProjectRoot ('engine\'+$name+'.psm1')
        if(-not(Test-Path -LiteralPath $module -PathType Leaf)){throw ('Required Safe Core engine module missing: '+$module)}
        Import-Module $module -Force -ErrorAction Stop
    }
    Import-MLLMTasks -ProjectRoot $ProjectRoot

    foreach($module in @(
        (Join-Path $ProjectRoot 'gui\GuiAdapter.psm1'),
        (Join-Path $ProjectRoot 'installer\InstallerPaths.psm1'),
        (Join-Path $ProjectRoot 'installer\InstallerState.psm1'),
        (Join-Path $ProjectRoot 'installer\Activation.psm1'),
        (Join-Path $ProjectRoot 'runtime\WorkbenchRuntimeAdapter.psm1')
    )){
        if(-not(Test-Path -LiteralPath $module -PathType Leaf)){throw ('Required backend module missing: '+$module)}
        Import-Module $module -Force -ErrorAction Stop
    }
    $script:SafeCoreReady=$true
}

function Convert-ComponentHealth {
    param([string]$Status,[string]$Summary)
    switch(([string]$Status).ToUpperInvariant()){
        'PASS'{return 'Pass'}
        'RUNNING'{return 'Running'}
        'READY_TO_INSTALL'{return 'ReadyToInstall'}
        'REPAIR_AVAILABLE'{return 'RepairAvailable'}
        'BLOCKED'{return 'Blocked'}
        'NOT_FOUND'{return 'NotFound'}
        'FAILED'{if(([string]$Summary).StartsWith('Detection failed',[StringComparison]::OrdinalIgnoreCase)){return 'DetectionError'};return 'OperationFailed'}
        default{return 'Unknown'}
    }
}

function Get-SafeGuiSnapshot {
    Initialize-SafeCore
    $snapshot=Get-MLLMGuiSnapshot -ProjectRoot $ProjectRoot -DataRoot $DataRoot -NetworkMode $NetworkMode
    $errors=@(Get-ObjectValue -Object $snapshot -Name 'errors' -Default @())
    if($errors.Count -gt 0){
        $messages=@($errors|ForEach-Object{[string](Get-ObjectValue -Object $_ -Name 'message' -Default ([string]$_))})
        throw ('BACKEND_DETECTION_ERROR|'+($messages -join ' | '))
    }
    return $snapshot
}

function Convert-GuiComponents {
    param($Snapshot)
    $rows=New-Object Collections.Generic.List[object]
    foreach($task in @(Get-ObjectValue -Object $Snapshot -Name 'tasks' -Default @())){
        $status=[string](Get-ObjectValue -Object $task -Name 'status' -Default '')
        $summary=[string](Get-ObjectValue -Object $task -Name 'summary' -Default '')
        $repairTask=[string](Get-ObjectValue -Object $task -Name 'repair_task' -Default '')
        $rows.Add([ordered]@{
            id=[string](Get-ObjectValue -Object $task -Name 'id' -Default 'unknown')
            health=Convert-ComponentHealth -Status $status -Summary $summary
            summary=$summary
            repairAvailable=[bool](Get-ObjectValue -Object $task -Name 'repair_available' -Default $false)
            repairTask=if($repairTask){$repairTask}else{$null}
        })
    }
    return $rows.ToArray()
}

function Get-MachineSnapshot {
    $cpu=[string]$env:PROCESSOR_IDENTIFIER
    [double]$ramGb=0
    $gpus=@()
    [double]$freeGb=0
    try{$processor=Get-CimInstance Win32_Processor -ErrorAction Stop|Select-Object -First 1;if($null -ne $processor -and $processor.Name){$cpu=[string]$processor.Name}}catch{}
    try{$computer=Get-CimInstance Win32_ComputerSystem -ErrorAction Stop;if($null -ne $computer.TotalPhysicalMemory){$ramGb=[Math]::Round(([double]$computer.TotalPhysicalMemory/1GB),2)}}catch{}
    try{$gpus=@(Get-CimInstance Win32_VideoController -ErrorAction Stop|ForEach-Object{[string]$_.Name}|Where-Object{$_})}catch{$gpus=@()}
    try{$fixed=@(Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3' -ErrorAction Stop);$sum=($fixed|Measure-Object -Property FreeSpace -Sum).Sum;if($null -ne $sum){$freeGb=[Math]::Round(([double]$sum/1GB),2)}}catch{}
    return [ordered]@{os=[Environment]::OSVersion.VersionString;architecture=[string]$env:PROCESSOR_ARCHITECTURE;cpu=$cpu;ramGb=$ramGb;gpus=@($gpus);fixedDiskFreeGb=$freeGb}
}

function Get-DesktopDashboardSnapshot {
    $snapshot=Get-SafeGuiSnapshot
    return [ordered]@{machine=Get-MachineSnapshot;networkMode=$NetworkMode;components=@(Convert-GuiComponents -Snapshot $snapshot);currentModel=$null}
}

function Get-DesktopDoctorSnapshot {
    $snapshot=Get-SafeGuiSnapshot
    return [ordered]@{components=@(Convert-GuiComponents -Snapshot $snapshot);errors=@()}
}

function Get-LastInstallerErrorMessage {
    param($State)
    if($null -eq $State){return $null}
    $errors=@(Get-ObjectValue -Object $State -Name 'errors' -Default @())
    if($errors.Count -eq 0){return $null}
    $last=$errors[$errors.Count-1]
    $message=[string](Get-ObjectValue -Object $last -Name 'message' -Default '')
    if($message){return $message}
    return ([string]$last)
}

function Get-DesktopInstallerSnapshot {
    Initialize-SafeCore
    $basePaths=Get-MLLMInstallerPaths -RunId 'desktop-readonly' -VersionId 'desktop-readonly'
    $state=Read-MLLMInstallerState -Path ([string]$basePaths.StatePath)
    $active=Get-MLLMActiveVersion -PointerPath ([string]$basePaths.CurrentPointer)
    $runId=$null;$versionId=$null;$stage='IDLE';$canResume=$false;$canRollback=$false
    $evidenceRoot=Join-Path $env:USERPROFILE 'Downloads\M_LLM_EVIDENCE'
    if($null -ne $state){
        $runId=[string](Get-ObjectValue -Object $state -Name 'run_id' -Default '')
        $versionId=[string](Get-ObjectValue -Object $state -Name 'version_id' -Default '')
        $stage=[string](Get-ObjectValue -Object $state -Name 'stage' -Default 'UNKNOWN')
        $canResume=($stage -ne 'COMPLETE')
        if($runId -and $versionId){$statePaths=Get-MLLMInstallerPaths -RunId $runId -VersionId $versionId;$evidenceRoot=[string]$statePaths.EvidencePreferredRoot}
    }
    $activeVersion=$null
    if($null -ne $active){
        $activeVersion=[string](Get-ObjectValue -Object $active -Name 'version_id' -Default '')
        $previous=Get-ObjectValue -Object $active -Name 'previous_version' -Default $null
        $canRollback=($null -ne $previous -and -not [string]::IsNullOrWhiteSpace([string](Get-ObjectValue -Object $previous -Name 'version_id' -Default '')))
    }
    return [ordered]@{runId=if($runId){$runId}else{$null};versionId=if($versionId){$versionId}else{$null};stage=$stage;canResume=$canResume;activeVersion=if($activeVersion){$activeVersion}else{$null};lastError=Get-LastInstallerErrorMessage -State $state;evidenceRoot=$evidenceRoot;canRollback=$canRollback}
}

function Require-PayloadString {
    param($Payload,[Parameter(Mandatory=$true)][string]$Name,[string]$ErrorCode='INVALID_PAYLOAD')
    $value=[string](Get-ObjectValue -Object $Payload -Name $Name -Default '')
    if([string]::IsNullOrWhiteSpace($value)){throw ($ErrorCode+'|'+$Name+' is required')}
    return $value
}

function Assert-OperationId {
    param($Payload)
    $operationId=Require-PayloadString -Payload $Payload -Name 'operationId' -ErrorCode 'INVALID_OPERATION_ID'
    if($operationId -notmatch '^[0-9a-fA-F]{32}$'){throw ('INVALID_OPERATION_ID|'+$operationId)}
    return $operationId
}

function Assert-ServiceId {
    param($Payload)
    $serviceId=Require-PayloadString -Payload $Payload -Name 'serviceId' -ErrorCode 'SERVICE_NOT_FOUND'
    if($serviceId -notin @('local-model-api','web-workbench')){throw ('SERVICE_NOT_FOUND|'+$serviceId)}
    return $serviceId
}

function Get-PhaseBModelSnapshot {
    Initialize-SafeCore
    $models=@(Get-MLLMModelInventory -ProjectRoot $ProjectRoot -DataRoot $DataRoot)
    $active=Get-MLLMActiveModel -DataRoot $DataRoot
    $activeId=$null
    if($null -ne $active){$activeId=[string](Get-ObjectValue -Object $active -Name 'modelId' -Default '')}
    return [ordered]@{models=$models;activeModelId=if($activeId){$activeId}else{$null};networkMode=$NetworkMode}
}

function Get-PhaseBServicesSnapshot {
    Initialize-SafeCore
    return [ordered]@{services=@(Get-MLLMWorkbenchServices -ProjectRoot $ProjectRoot -DataRoot $DataRoot -NetworkMode $NetworkMode);networkMode=$NetworkMode}
}

function Get-PhaseBServiceDescriptor {
    param([Parameter(Mandatory=$true)][string]$ServiceId)
    $rows=@(Get-MLLMWorkbenchServices -ProjectRoot $ProjectRoot -DataRoot $DataRoot -NetworkMode $NetworkMode | Where-Object {[string]$_.serviceId -eq $ServiceId})
    if($rows.Count -ne 1){throw ('SERVICE_NOT_FOUND|'+$ServiceId)}
    return $rows[0]
}

function Invoke-PhaseBModelVerify {
    param($Payload)
    Initialize-SafeCore
    [void](Assert-OperationId -Payload $Payload)
    $modelId=Require-PayloadString -Payload $Payload -Name 'modelId' -ErrorCode 'MODEL_NOT_FOUND'
    return (Test-MLLMWorkbenchModel -ProjectRoot $ProjectRoot -DataRoot $DataRoot -ModelId $modelId)
}

function Invoke-PhaseBModelImport {
    param($Payload)
    Initialize-SafeCore
    [void](Assert-OperationId -Payload $Payload)
    $source=Require-PayloadString -Payload $Payload -Name 'sourcePath' -ErrorCode 'MODEL_IMPORT_FAILED'
    if($source.StartsWith('\\',[StringComparison]::Ordinal)){throw 'MODEL_IMPORT_SOURCE_NOT_LOCAL|UNC model paths are not accepted'}
    $source=[IO.Path]::GetFullPath($source)
    if(-not(Test-Path -LiteralPath $source -PathType Leaf)){throw ('MODEL_NOT_FOUND|'+$source)}
    if([IO.Path]::GetExtension($source) -ne '.gguf'){throw 'MODEL_FORMAT_INVALID|Managed import accepts .gguf files only'}
    $display=[string](Get-ObjectValue -Object $Payload -Name 'displayName' -Default '')
    return (Import-MLLMManagedModel -ProjectRoot $ProjectRoot -DataRoot $DataRoot -SourcePath $source -DisplayName $display)
}

function Invoke-PhaseBModelActivate {
    param($Payload)
    Initialize-SafeCore
    [void](Assert-OperationId -Payload $Payload)
    $modelId=Require-PayloadString -Payload $Payload -Name 'modelId' -ErrorCode 'MODEL_NOT_FOUND'
    Set-MLLMActiveModel -ProjectRoot $ProjectRoot -DataRoot $DataRoot -ModelId $modelId | Out-Null
    return (Test-MLLMWorkbenchModel -ProjectRoot $ProjectRoot -DataRoot $DataRoot -ModelId $modelId)
}

function Invoke-PhaseBServiceAction {
    param($Payload,[Parameter(Mandatory=$true)][ValidateSet('start','stop','restart')][string]$Action)
    Initialize-SafeCore
    [void](Assert-OperationId -Payload $Payload)
    $serviceId=Assert-ServiceId -Payload $Payload
    switch($Action){
        'start'{Start-MLLMWorkbenchService -ProjectRoot $ProjectRoot -DataRoot $DataRoot -NetworkMode $NetworkMode -ServiceId $serviceId | Out-Null}
        'stop'{Stop-MLLMWorkbenchService -ProjectRoot $ProjectRoot -DataRoot $DataRoot -ServiceId $serviceId | Out-Null}
        'restart'{Restart-MLLMWorkbenchService -ProjectRoot $ProjectRoot -DataRoot $DataRoot -NetworkMode $NetworkMode -ServiceId $serviceId | Out-Null}
    }
    return (Get-PhaseBServiceDescriptor -ServiceId $serviceId)
}

function Invoke-PhaseBServiceLogs {
    param($Payload)
    Initialize-SafeCore
    $serviceId=Assert-ServiceId -Payload $Payload
    $tail=[int](Get-ObjectValue -Object $Payload -Name 'tailLines' -Default 0)
    if($tail -lt 1 -or $tail -gt 500){throw ('SERVICE_LOG_TAIL_INVALID|'+$tail)}
    return (Get-MLLMWorkbenchServiceLogs -DataRoot $DataRoot -ServiceId $serviceId -TailLines $tail)
}

function Get-ComponentPresetDefinitions {
    Initialize-SafeCore
    $policyPath=Join-Path $ProjectRoot 'config\task-policy.json'
    if(-not(Test-Path -LiteralPath $policyPath -PathType Leaf)){throw ('PRESET_POLICY_MISSING|'+$policyPath)}
    $policy=Get-Content -LiteralPath $policyPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $specs=@(
        [ordered]@{id='full-setup';name='Full Setup';description='完整本地 AI 栈：Git、Git LFS、Python、ModelScope、llama.cpp、Qwen3.5-4B、Local API、Web Workbench';recommended=$true},
        [ordered]@{id='local-ai-fast';name='Local AI Fast';description='本地快速推理：Python、ModelScope、llama.cpp、Qwen3.5-4B、Local API';recommended=$false},
        [ordered]@{id='core';name='Core';description='基础运行环境：Python、ModelScope、llama.cpp';recommended=$false},
        [ordered]@{id='web-workbench';name='Web Workbench';description='本地 AI 栈加 Web Workbench';recommended=$false},
        [ordered]@{id='developer-tools';name='Developer Tools';description='开发工具：Git、Git LFS';recommended=$false}
    )
    $rows=New-Object Collections.Generic.List[object]
    foreach($spec in $specs){
        $presetName=[string]$spec.name
        if(-not($policy.presets.PSObject.Properties.Name -contains $presetName)){throw ('PRESET_POLICY_INVALID|'+$presetName)}
        $rows.Add([ordered]@{
            id=[string]$spec.id
            displayName=$presetName
            description=[string]$spec.description
            recommended=[bool]$spec.recommended
            components=@($policy.presets.$presetName)
        })
    }
    return $rows.ToArray()
}

function Resolve-ComponentPresetDefinition {
    param([Parameter(Mandatory=$true)][string]$PresetId)
    $rows=@(Get-ComponentPresetDefinitions | Where-Object {[string]$_.id -eq $PresetId})
    if($rows.Count -ne 1){throw ('PRESET_NOT_ALLOWED|'+$PresetId)}
    return $rows[0]
}

function Invoke-ComponentPresetInstall {
    param($Payload)
    Initialize-SafeCore
    [void](Assert-OperationId -Payload $Payload)
    $presetId=Require-PayloadString -Payload $Payload -Name 'presetId' -ErrorCode 'PRESET_NOT_ALLOWED'
    $preset=Resolve-ComponentPresetDefinition -PresetId $presetId
    $runDir=Start-MLLMRunLog -Root $DataRoot
    $results=@(Invoke-MLLMPreset -Preset ([string]$preset.displayName) -ProjectRoot $ProjectRoot -DataRoot $DataRoot -NetworkMode $NetworkMode -RunDir $runDir)
    $mapped=New-Object Collections.Generic.List[object]
    foreach($item in $results){
        $mapped.Add([ordered]@{
            id=[string](Get-ObjectValue -Object $item -Name 'id' -Default 'unknown')
            status=[string](Get-ObjectValue -Object $item -Name 'status' -Default 'UNKNOWN')
            summary=[string](Get-ObjectValue -Object $item -Name 'summary' -Default '')
        })
    }
    return [ordered]@{presetId=$presetId;displayName=[string]$preset.displayName;results=$mapped.ToArray()}
}

function New-RpcError {
    param([string]$Code,[string]$Message,[bool]$Recoverable=$true)
    return [ordered]@{code=$Code;message=$Message;stage='RPC';recoverable=$Recoverable;details=$null}
}

function Write-RpcResponse {
    param($Writer,[string]$Id,[bool]$Success,$Payload,$ErrorObject)
    $response=[ordered]@{protocol='1.0';type='response';id=$Id;success=$Success;payload=$Payload;error=$ErrorObject}
    $Writer.WriteLine(($response|ConvertTo-Json -Depth 24 -Compress))
    $Writer.Flush()
}

$MethodTable=@{
    'system.ping' = { param($Payload) return [ordered]@{status='PASS';backendVersion='phase-b'} }
    'dashboard.snapshot' = { param($Payload) return (Get-DesktopDashboardSnapshot) }
    'doctor.snapshot' = { param($Payload) return (Get-DesktopDoctorSnapshot) }
    'installer.snapshot' = { param($Payload) return (Get-DesktopInstallerSnapshot) }
    'system.capabilities' = { param($Payload) return [ordered]@{backendVersion='phase-b';methods=@($MethodTable.Keys)} }
    'models.snapshot' = { param($Payload) return (Get-PhaseBModelSnapshot) }
    'models.verify' = { param($Payload) return (Invoke-PhaseBModelVerify -Payload $Payload) }
    'models.import' = { param($Payload) return (Invoke-PhaseBModelImport -Payload $Payload) }
    'models.activate' = { param($Payload) return (Invoke-PhaseBModelActivate -Payload $Payload) }
    'services.snapshot' = { param($Payload) return (Get-PhaseBServicesSnapshot) }
    'service.start' = { param($Payload) return (Invoke-PhaseBServiceAction -Payload $Payload -Action start) }
    'service.stop' = { param($Payload) return (Invoke-PhaseBServiceAction -Payload $Payload -Action stop) }
    'service.restart' = { param($Payload) return (Invoke-PhaseBServiceAction -Payload $Payload -Action restart) }
    'service.logs' = { param($Payload) return (Invoke-PhaseBServiceLogs -Payload $Payload) }
    'components.presets' = { param($Payload) return [ordered]@{presets=@(Get-ComponentPresetDefinitions)} }
    'components.install_preset' = { param($Payload) return (Invoke-ComponentPresetInstall -Payload $Payload) }
}

$currentSid=[Security.Principal.WindowsIdentity]::GetCurrent().User
$adminSid=New-Object System.Security.Principal.SecurityIdentifier('S-1-5-32-544')
$pipeSecurity=New-Object System.IO.Pipes.PipeSecurity
$rights=[System.IO.Pipes.PipeAccessRights]::ReadWrite
$allow=[Security.AccessControl.AccessControlType]::Allow
$pipeSecurity.AddAccessRule((New-Object System.IO.Pipes.PipeAccessRule($currentSid,$rights,$allow)))
$pipeSecurity.AddAccessRule((New-Object System.IO.Pipes.PipeAccessRule($adminSid,$rights,$allow)))
$direction=[System.IO.Pipes.PipeDirection]::InOut
$transmission=[System.IO.Pipes.PipeTransmissionMode]::Byte
$options=[System.IO.Pipes.PipeOptions]::Asynchronous
$pipe=New-Object System.IO.Pipes.NamedPipeServerStream -ArgumentList @($PipeName,$direction,1,$transmission,$options,4096,4096,$pipeSecurity)
$utf8=New-Object System.Text.UTF8Encoding($false)
$reader=$null
$writer=$null
try{
    Write-Output 'WORKBENCH_BACKEND=STARTING protocol=1.0'
    $pipe.WaitForConnection()
    $reader=New-Object System.IO.StreamReader -ArgumentList @($pipe,$utf8,$false,4096,$true)
    $writer=New-Object System.IO.StreamWriter -ArgumentList @($pipe,$utf8,4096,$true)
    $writer.AutoFlush=$true
    $firstLine=$reader.ReadLine()
    if(-not $firstLine){exit 11}
    try{$first=$firstLine|ConvertFrom-Json}catch{exit 12}
    if(([string]$first.type) -ne 'handshake'){
        Write-RpcResponse -Writer $writer -Id ([string]$first.id) -Success $false -Payload $null -ErrorObject (New-RpcError 'HANDSHAKE_REQUIRED' 'The first backend request must be a handshake.' $false)
        exit 13
    }
    if(([string]$first.protocol) -ne '1.0'){
        Write-RpcResponse -Writer $writer -Id ([string]$first.id) -Success $true -Payload ([ordered]@{accepted=$false;protocol='1.0';backendVersion='phase-b';error='Protocol mismatch'}) -ErrorObject $null
        exit 14
    }
    if(-not(Test-SessionToken -Actual ([string]$first.sessionToken) -Expected $SessionToken)){
        Write-RpcResponse -Writer $writer -Id ([string]$first.id) -Success $true -Payload ([ordered]@{accepted=$false;protocol='1.0';backendVersion='phase-b';error='Authentication failed'}) -ErrorObject $null
        exit 15
    }
    Write-RpcResponse -Writer $writer -Id ([string]$first.id) -Success $true -Payload ([ordered]@{accepted=$true;protocol='1.0';backendVersion='phase-b';error=$null}) -ErrorObject $null
    Write-Output 'WORKBENCH_BACKEND=AUTHENTICATED'

    while($pipe.IsConnected){
        $line=$reader.ReadLine()
        if($null -eq $line){break}
        if(-not $line){continue}
        try{$request=$line|ConvertFrom-Json}catch{Write-RpcResponse -Writer $writer -Id '' -Success $false -Payload $null -ErrorObject (New-RpcError 'INVALID_JSON' 'Malformed request JSON.' $true);continue}
        $id=[string]$request.id
        if(([string]$request.protocol) -ne '1.0'){
            Write-RpcResponse -Writer $writer -Id $id -Success $false -Payload $null -ErrorObject (New-RpcError 'PROTOCOL_MISMATCH' 'Protocol version mismatch.' $false)
            continue
        }
        if(-not(Test-SessionToken -Actual ([string]$request.sessionToken) -Expected $SessionToken)){
            Write-RpcResponse -Writer $writer -Id $id -Success $false -Payload $null -ErrorObject (New-RpcError 'AUTH_FAILED' 'Session authentication failed.' $false)
            break
        }
        $method=[string]$request.method
        if(-not $MethodTable.ContainsKey($method)){
            Write-RpcResponse -Writer $writer -Id $id -Success $false -Payload $null -ErrorObject (New-RpcError 'METHOD_NOT_FOUND' ('Method is not allowed: '+$method) $true)
            continue
        }
        try{
            $payload=$null
            if($request.PSObject.Properties['payload']){$payload=$request.payload}
            $result=& $MethodTable[$method] $payload
            Write-RpcResponse -Writer $writer -Id $id -Success $true -Payload $result -ErrorObject $null
        }catch{
            $message=[string]$_.Exception.Message
            $code='BACKEND_OPERATION_FAILED'
            if($message -match '^([A-Z][A-Z0-9_]+)\|(.*)$'){
                $code=$Matches[1]
                $message=$Matches[2]
            }
            Write-RpcResponse -Writer $writer -Id $id -Success $false -Payload $null -ErrorObject (New-RpcError $code $message $true)
        }
    }
}finally{
    if($null -ne $writer){$writer.Dispose()}
    if($null -ne $reader){$reader.Dispose()}
    $pipe.Dispose()
    Write-Output 'WORKBENCH_BACKEND=STOPPED'
}
