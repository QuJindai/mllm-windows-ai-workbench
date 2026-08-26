$ErrorActionPreference='Stop'
Set-StrictMode -Version 2
$Root=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$Data=Join-Path $env:TEMP ('mllm-safe-core-'+[guid]::NewGuid().ToString('N'))

function Assert-True([bool]$Condition,[string]$Message){if(-not $Condition){throw $Message}}

$oldPath=$env:Path
$oldLocalAppData=$env:LOCALAPPDATA
$oldProgramFiles=$env:ProgramFiles
try{
    foreach($m in @('Core','State','Detection','Network','Download','Security','Evidence','Runtime')){
        Import-Module (Join-Path $Root "engine\$m.psm1") -Force -ErrorAction Stop
    }
    Initialize-MLLMStateStore -Root $Data | Out-Null
    Import-MLLMTasks -ProjectRoot $Root

    $policy=Get-Content (Join-Path $Root 'config\task-policy.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $core=@($policy.presets.Core)
    Assert-True ($core -contains 'python') 'Core must include python task.'
    Assert-True ($core -contains 'modelscope') 'Core must include modelscope task.'
    Assert-True ($core -contains 'llama-cpp') 'Core must include llama-cpp task.'
    Assert-True (-not($core -contains 'git')) 'Core must not include Git.'
    Assert-True (-not($core -contains 'git-lfs')) 'Core must not include Git LFS.'

    # Force the process into a no-Python view so the portable fallback path is
    # exercised. Do not alter machine/user environment; these are process-local.
    $env:Path="$env:SystemRoot\System32;$env:SystemRoot"
    $env:LOCALAPPDATA=Join-Path $Data 'fake-localappdata'
    $env:ProgramFiles=Join-Path $Data 'fake-programfiles'

    # Exercise the exact Install Center "Core" orchestration path first. With
    # OFFLINE_CACHE and an empty cache it must fail closed: return BLOCKED and
    # make no executable/system installation changes.
    $presetResult=Invoke-MLLMPreset -Preset 'Core' -ProjectRoot $Root -DataRoot $Data -NetworkMode 'OFFLINE_CACHE' -RunDir ''
    $presetItems=@($presetResult | ForEach-Object {$_})
    Assert-True ($presetItems.Count -ge 1) 'Core preset returned no result.'
    Assert-True (@($presetItems | Where-Object {$_.status -eq 'BLOCKED'}).Count -ge 1) 'Offline empty-cache Core preset must return BLOCKED.'
    Assert-True (@($presetItems | Where-Object {$_.status -eq 'FAILED'}).Count -eq 0) 'Offline empty-cache Core preset must not crash/fail.'
    Assert-True (-not(Test-Path (Join-Path $Data 'runtime\python-portable\python.exe'))) 'Blocked Core preset unexpectedly created Python executable.'
    Assert-True (-not(Test-Path (Join-Path $Data 'runtime\llama.cpp\llama-server.exe'))) 'Blocked Core preset unexpectedly created llama-server executable.'
    Write-Host 'SAFE_CORE_PRESET_OFFLINE=PASS'

    # Also exercise each installer handler independently so one blocked upstream
    # dependency cannot hide an unsafe downstream behavior.
    $ctx=@{ProjectRoot=$Root;DataRoot=$Data;NetworkMode='OFFLINE_CACHE';RunDir=''}
    $py=Invoke-MLLMTask -Id 'python' -Action Install -Context $ctx
    Assert-True ($py.status -eq 'BLOCKED') ("Offline empty-cache Python must BLOCK, got: "+$py.status)
    Assert-True (-not(Test-Path (Join-Path $Data 'runtime\python-portable\python.exe'))) 'Blocked Python install unexpectedly created an executable.'

    $ms=Invoke-MLLMTask -Id 'modelscope' -Action Install -Context $ctx
    Assert-True ($ms.status -eq 'BLOCKED') ("ModelScope without Python must BLOCK, got: "+$ms.status)

    $llama=Invoke-MLLMTask -Id 'llama-cpp' -Action Install -Context $ctx
    Assert-True ($llama.status -eq 'BLOCKED') ("Offline empty-cache llama.cpp must BLOCK, got: "+$llama.status)
    Assert-True (-not(Test-Path (Join-Path $Data 'runtime\llama.cpp\llama-server.exe'))) 'Blocked llama.cpp install unexpectedly created an executable.'

    Write-Host 'SAFE_CORE_OFFLINE_INSTALL=PASS'
}finally{
    $env:Path=$oldPath
    $env:LOCALAPPDATA=$oldLocalAppData
    $env:ProgramFiles=$oldProgramFiles
    Remove-Item -LiteralPath $Data -Recurse -Force -ErrorAction SilentlyContinue
}
