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

function New-RpcError {
    param([string]$Code,[string]$Message,[bool]$Recoverable=$true)
    return [ordered]@{code=$Code;message=$Message;stage='RPC';recoverable=$Recoverable;details=$null}
}

function Write-RpcResponse {
    param($Writer,[string]$Id,[bool]$Success,$Payload,$ErrorObject)
    $response=[ordered]@{
        protocol='1.0'
        type='response'
        id=$Id
        success=$Success
        payload=$Payload
        error=$ErrorObject
    }
    $Writer.WriteLine(($response|ConvertTo-Json -Depth 20 -Compress))
    $Writer.Flush()
}

$MethodTable=@{
    'system.ping' = { param($Payload) return [ordered]@{status='PASS';backendVersion='phase-a'} }
}

$currentSid=[Security.Principal.WindowsIdentity]::GetCurrent().User
$adminSid=New-Object Security.Principal.SecurityIdentifier('S-1-5-32-544')
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
        Write-RpcResponse -Writer $writer -Id ([string]$first.id) -Success $true -Payload ([ordered]@{accepted=$false;protocol='1.0';backendVersion='phase-a';error='Protocol mismatch'}) -ErrorObject $null
        exit 14
    }
    if(-not(Test-SessionToken -Actual ([string]$first.sessionToken) -Expected $SessionToken)){
        Write-RpcResponse -Writer $writer -Id ([string]$first.id) -Success $true -Payload ([ordered]@{accepted=$false;protocol='1.0';backendVersion='phase-a';error='Authentication failed'}) -ErrorObject $null
        exit 15
    }
    Write-RpcResponse -Writer $writer -Id ([string]$first.id) -Success $true -Payload ([ordered]@{accepted=$true;protocol='1.0';backendVersion='phase-a';error=$null}) -ErrorObject $null
    Write-Output 'WORKBENCH_BACKEND=AUTHENTICATED'

    while($pipe.IsConnected){
        $line=$reader.ReadLine()
        if($null -eq $line){break}
        if(-not $line){continue}
        try{$request=$line|ConvertFrom-Json}catch{
            Write-RpcResponse -Writer $writer -Id '' -Success $false -Payload $null -ErrorObject (New-RpcError 'INVALID_JSON' 'Malformed request JSON.' $true)
            continue
        }
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
            Write-RpcResponse -Writer $writer -Id $id -Success $false -Payload $null -ErrorObject (New-RpcError 'BACKEND_OPERATION_FAILED' $_.Exception.Message $true)
        }
    }
}finally{
    if($null -ne $writer){$writer.Dispose()}
    if($null -ne $reader){$reader.Dispose()}
    $pipe.Dispose()
    Write-Output 'WORKBENCH_BACKEND=STOPPED'
}
