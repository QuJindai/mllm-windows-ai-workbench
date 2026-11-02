#Requires -Version 7.0
[CmdletBinding()]
param([string]$DreamRoot = 'E:\Dream', [string]$DepthModel)
$ErrorActionPreference = 'Stop'
$pack = (Resolve-Path (Join-Path $PSScriptRoot '../config/dream/hq-paired-depth-v1')).Path
$settings = Get-Content -LiteralPath (Join-Path $DreamRoot 'data/hq/config.json') -Raw | ConvertFrom-Json
$target = (Resolve-Path -LiteralPath $settings.pipelineConfig).Path
$config = Get-Content -LiteralPath $target -Raw | ConvertFrom-Json -AsHashtable
if (-not $DepthModel) {
    $DepthModel = Join-Path (Split-Path $config.controlnet) 'control_v11f1p_sd15_depth.pth'
}
$modelPath = (Resolve-Path -LiteralPath $DepthModel).Path
function Assert-DreamHash([string]$File, [string]$Expected) {
    if ((Get-FileHash -LiteralPath $File -Algorithm SHA256).Hash -ne $Expected) {
        throw "HQ checksum mismatch: $File"
    }
}
Assert-DreamHash $modelPath '761077ffe369fe8cf16ae353f8226bd4ca29805b161052f82c0170c7b50f1d99'
$modelConfig = Join-Path $pack 'controlnet'
Assert-DreamHash (Join-Path $modelConfig 'config.json') 'ee789f6b46cd8c443c80ffb81e5c05e14b8b3cbec9e861829bfa3d2a6d3ee16f'
$manifest = Get-Content -LiteralPath (Join-Path $pack 'manifest.json') -Raw | ConvertFrom-Json
foreach ($item in $manifest.items) {
    if ($item.depthSha256 -cnotmatch '^[0-9a-f]{64}$') { throw 'Invalid depth digest' }
    Assert-DreamHash (Join-Path $pack ($item.depthSha256+'.webp')) $item.depthSha256
}
if ($config.poseEstimator -eq $manifest.poseEstimator -and $config.controlnet -eq $modelPath -and
    $config.controlnetConfig -eq $modelConfig -and $config.poseScale -eq .9 -and $config.garmentScale -eq .7 -and $config.offload -eq 'sequential') {
    Write-Output 'HQ paired depth already enabled'
    return
}
$config.controlnet = $modelPath
$config.controlnetConfig = $modelConfig
$config.poseEstimator = $manifest.poseEstimator
$config.poseScale = .9
$config.garmentScale = .7
$config.offload = 'sequential'
$temporary = $target + '.' + [guid]::NewGuid().ToString('N') + '.tmp'
$backup = $target + '.pre-depth-' + (Get-Date -Format yyyyMMdd-HHmmss-fffffff) + '.bak'
try {
    [IO.File]::WriteAllText($temporary, ($config | ConvertTo-Json -Depth 8), [Text.UTF8Encoding]::new($false))
    [IO.File]::Replace($temporary, $target, $backup)
} finally {
    if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary }
}
Write-Output "HQ paired depth enabled ($($manifest.items.Count) poses). Previous config: $backup"
