Set-StrictMode -Version 2
$ErrorActionPreference='Stop'

$stateModule=Join-Path $PSScriptRoot 'InstallerState.psm1'
if(-not(Get-Command Save-MLLMInstallerState -ErrorAction SilentlyContinue)){
    if(-not(Test-Path -LiteralPath $stateModule -PathType Leaf)){throw 'InstallerState.psm1 missing'}
    Import-Module $stateModule -Force -ErrorAction Stop
}

function Get-MLLMFileSha256 {
    param([Parameter(Mandatory=$true)][string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant()
}

function Get-MLLMSourceManifest {
    [CmdletBinding()]
    param([Parameter(Mandatory=$true)][ValidateNotNullOrEmpty()][string]$Path)

    if(-not(Test-Path -LiteralPath $Path -PathType Leaf)){throw "Source manifest missing: $Path"}
    $manifest=Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
    if([string]$manifest.schema -ne 'mllm.universal-installer.sources.v1'){
        throw "Unsupported source manifest schema: $($manifest.schema)"
    }
    if($null -eq $manifest.packages){throw 'Source manifest packages collection is missing'}
    return $manifest
}

function Invoke-MLLMBitsDownload {
    param(
        [Parameter(Mandatory=$true)][string]$Uri,
        [Parameter(Mandatory=$true)][string]$DestinationPartial,
        [Parameter(Mandatory=$true)][int]$TimeoutSeconds
    )

    $cmd=Get-Command Start-BitsTransfer -ErrorAction SilentlyContinue
    if($null -eq $cmd){throw 'BITS_UNAVAILABLE'}
    $job=$null
    try{
        $job=Start-BitsTransfer -Source $Uri -Destination $DestinationPartial -Asynchronous -ErrorAction Stop
        $deadline=(Get-Date).AddSeconds([Math]::Max(1,$TimeoutSeconds))
        while((Get-Date) -lt $deadline){
            $job=Get-BitsTransfer -Id $job.Id -ErrorAction Stop
            $state=[string]$job.JobState
            if($state -eq 'Transferred'){
                Complete-BitsTransfer -BitsJob $job -ErrorAction Stop
                return [pscustomobject]@{method='BITS';path=$DestinationPartial}
            }
            if($state -in @('Error','TransientError','Cancelled')){
                $detail=[string]$job.ErrorDescription
                throw "BITS_$state $detail"
            }
            Start-Sleep -Milliseconds 200
        }
        throw "BITS_TIMEOUT after $TimeoutSeconds seconds"
    }finally{
        if($null -ne $job){
            try{
                $current=Get-BitsTransfer -Id $job.Id -ErrorAction SilentlyContinue
                if($null -ne $current){Remove-BitsTransfer -BitsJob $current -Confirm:$false -ErrorAction SilentlyContinue}
            }catch{}
        }
    }
}

function Invoke-MLLMHttpClientDownload {
    param(
        [Parameter(Mandatory=$true)][string]$Uri,
        [Parameter(Mandatory=$true)][string]$DestinationPartial,
        [Parameter(Mandatory=$true)][int]$TimeoutSeconds,
        [string]$ProxyUri=''
    )

    $handler=New-Object Net.Http.HttpClientHandler
    if($ProxyUri){
        $handler.Proxy=New-Object Net.WebProxy($ProxyUri,$true)
        $handler.UseProxy=$true
    }
    $client=New-Object Net.Http.HttpClient($handler)
    $client.Timeout=[TimeSpan]::FromSeconds([Math]::Max(1,$TimeoutSeconds))
    $response=$null
    $input=$null
    $output=$null
    try{
        $response=$client.GetAsync($Uri,[Net.Http.HttpCompletionOption]::ResponseHeadersRead).GetAwaiter().GetResult()
        if(-not $response.IsSuccessStatusCode){throw "HTTP_STATUS_$([int]$response.StatusCode) $($response.ReasonPhrase)"}
        $input=$response.Content.ReadAsStreamAsync().GetAwaiter().GetResult()
        $output=New-Object IO.FileStream($DestinationPartial,[IO.FileMode]::Create,[IO.FileAccess]::Write,[IO.FileShare]::None)
        $input.CopyTo($output)
        $output.Flush($true)
        return [pscustomobject]@{method='HTTPCLIENT';path=$DestinationPartial;status_code=[int]$response.StatusCode}
    }finally{
        if($null -ne $output){$output.Dispose()}
        if($null -ne $input){$input.Dispose()}
        if($null -ne $response){$response.Dispose()}
        $client.Dispose()
        $handler.Dispose()
    }
}

function Invoke-MLLMHttpDownload {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)][ValidateNotNullOrEmpty()][string]$Uri,
        [Parameter(Mandatory=$true)][ValidateNotNullOrEmpty()][string]$DestinationPartial,
        [int]$TimeoutSeconds=20,
        [bool]$PreferBits=$true,
        [string]$ProxyUri=''
    )

    $dir=Split-Path -Parent ([IO.Path]::GetFullPath($DestinationPartial))
    if(-not(Test-Path -LiteralPath $dir -PathType Container)){New-Item -ItemType Directory -Force -Path $dir | Out-Null}
    if(Test-Path -LiteralPath $DestinationPartial -PathType Leaf){Remove-Item -LiteralPath $DestinationPartial -Force}

    $bitsError=$null
    if($PreferBits){
        try{return Invoke-MLLMBitsDownload -Uri $Uri -DestinationPartial $DestinationPartial -TimeoutSeconds $TimeoutSeconds}
        catch{$bitsError=$_.Exception.Message;if(Test-Path -LiteralPath $DestinationPartial -PathType Leaf){Remove-Item -LiteralPath $DestinationPartial -Force -ErrorAction SilentlyContinue}}
    }
    try{
        return Invoke-MLLMHttpClientDownload -Uri $Uri -DestinationPartial $DestinationPartial -TimeoutSeconds $TimeoutSeconds -ProxyUri $ProxyUri
    }catch{
        if($bitsError){throw "BITS failed: $bitsError; HttpClient failed: $($_.Exception.Message)"}
        throw
    }
}

function Add-MLLMSourceAttempt {
    param(
        [Parameter(Mandatory=$true)]$State,
        [Parameter(Mandatory=$true)]$Attempt,
        [Parameter(Mandatory=$true)][string]$StatePath
    )
    $State.source_attempts=@($State.source_attempts)+@($Attempt)
    Save-MLLMInstallerState -State $State -Path $StatePath | Out-Null
}

function Invoke-MLLMAcquirePackage {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)]$Package,
        [Parameter(Mandatory=$true)][ValidateNotNullOrEmpty()][string]$CacheRoot,
        [Parameter(Mandatory=$true)]$State,
        [Parameter(Mandatory=$true)][ValidateNotNullOrEmpty()][string]$StatePath
    )

    $allowed=@('local_file','local_cache','http','github','custom_proxy')
    $expected=([string]$Package.sha256).ToLowerInvariant()
    if($expected -notmatch '^[0-9a-f]{64}$'){throw "Package SHA256 is invalid: $($Package.id)"}
    if(-not @($Package.sources).Count){throw "Package has no sources: $($Package.id)"}

    $fileName=[string]$Package.file_name
    if(-not $fileName){$fileName=([string]$Package.id)+'-'+([string]$Package.version)+'.pkg'}
    $packageDir=Join-Path ([IO.Path]::GetFullPath($CacheRoot)) (([string]$Package.id)+'\'+([string]$Package.version))
    if(-not(Test-Path -LiteralPath $packageDir -PathType Container)){New-Item -ItemType Directory -Force -Path $packageDir | Out-Null}
    $final=Join-Path $packageDir $fileName

    foreach($source in @($Package.sources)){
        $started=Get-Date
        $sourceId=[string]$source.id
        $kind=[string]$source.kind
        $attempt=[ordered]@{
            source_id=$sourceId
            kind=$kind
            status='RUNNING'
            error=$null
            started_at=$started.ToString('o')
            finished_at=$null
        }
        $partial=$final+'.partial.'+[guid]::NewGuid().ToString('N')
        try{
            if($allowed -notcontains $kind){throw "Unsupported source kind: $kind"}
            switch($kind){
                'local_file' {
                    $src=[string]$source.path
                    if(-not(Test-Path -LiteralPath $src -PathType Leaf)){throw "Local source missing: $src"}
                    Copy-Item -LiteralPath $src -Destination $partial -Force -ErrorAction Stop
                }
                'local_cache' {
                    $src=[string]$source.path
                    if(-not $src){$src=$final}
                    if(-not(Test-Path -LiteralPath $src -PathType Leaf)){throw "Cache source missing: $src"}
                    $cachedSha=Get-MLLMFileSha256 -Path $src
                    if($cachedSha -ne $expected){throw "Cache SHA256 mismatch expected=$expected actual=$cachedSha"}
                    if([IO.Path]::GetFullPath($src) -ne [IO.Path]::GetFullPath($final)){Copy-Item -LiteralPath $src -Destination $partial -Force -ErrorAction Stop}else{$partial=$src}
                }
                default {
                    $uri=[string]$source.uri
                    if(-not $uri){throw "Network source URI missing: $sourceId"}
                    $timeout=20
                    if($null -ne $source.PSObject.Properties['timeout_seconds']){$timeout=[int]$source.timeout_seconds}
                    $preferBits=$true
                    if($null -ne $source.PSObject.Properties['prefer_bits']){$preferBits=[bool]$source.prefer_bits}
                    $proxy=''
                    if($kind -eq 'custom_proxy' -and $null -ne $source.PSObject.Properties['proxy_uri']){$proxy=[string]$source.proxy_uri}
                    Invoke-MLLMHttpDownload -Uri $uri -DestinationPartial $partial -TimeoutSeconds $timeout -PreferBits $preferBits -ProxyUri $proxy | Out-Null
                }
            }

            $candidate=$partial
            $actual=Get-MLLMFileSha256 -Path $candidate
            if($actual -ne $expected){throw "SHA256 mismatch expected=$expected actual=$actual"}

            if([IO.Path]::GetFullPath($candidate) -ne [IO.Path]::GetFullPath($final)){
                if(Test-Path -LiteralPath $final -PathType Leaf){Remove-Item -LiteralPath $final -Force}
                Move-Item -LiteralPath $candidate -Destination $final -Force -ErrorAction Stop
            }
            $attempt.status='PASS'
            $attempt.finished_at=(Get-Date).ToString('o')
            Add-MLLMSourceAttempt -State $State -Attempt ([pscustomobject]$attempt) -StatePath $StatePath
            $State.selected_source=$sourceId
            $State.package_sha256=$expected
            Save-MLLMInstallerState -State $State -Path $StatePath | Out-Null
            return [pscustomobject]@{path=$final;source_id=$sourceId;sha256=$expected;kind=$kind}
        }catch{
            if(Test-Path -LiteralPath $partial -PathType Leaf){
                if([IO.Path]::GetFullPath($partial) -ne [IO.Path]::GetFullPath($final)){Remove-Item -LiteralPath $partial -Force -ErrorAction SilentlyContinue}
            }
            $attempt.status='FAILED'
            $attempt.error=$_.Exception.Message
            $attempt.finished_at=(Get-Date).ToString('o')
            Add-MLLMSourceAttempt -State $State -Attempt ([pscustomobject]$attempt) -StatePath $StatePath
        }
    }

    throw "All acquisition sources failed for package $($Package.id)"
}

Export-ModuleMember -Function Get-MLLMSourceManifest,Invoke-MLLMAcquirePackage,Invoke-MLLMHttpDownload
