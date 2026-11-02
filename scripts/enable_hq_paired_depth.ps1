#Requires -Version 7.0
[CmdletBinding()]
param([string]$DreamRoot = 'E:\Dream', [string]$DepthModel, [string]$OpenPoseModel, [string]$OpenPoseConfig)
$ErrorActionPreference = 'Stop'
$pack = (Resolve-Path (Join-Path $PSScriptRoot '../config/dream/hq-paired-depth-v1')).Path
$settings = Get-Content -LiteralPath (Join-Path $DreamRoot 'data/hq/config.json') -Raw | ConvertFrom-Json
$target = (Resolve-Path -LiteralPath $settings.pipelineConfig).Path
$config = Get-Content -LiteralPath $target -Raw | ConvertFrom-Json -AsHashtable
if (-not $DepthModel) {
    $DepthModel = Join-Path (Split-Path $config.controlnet) 'control_v11f1p_sd15_depth.pth'
}
$modelPath = (Resolve-Path -LiteralPath $DepthModel).Path
if (-not $OpenPoseModel) {
    $OpenPoseModel = if ($config.openpose.controlnet) { $config.openpose.controlnet }
        elseif ($config.poseEstimator -ne 'paired-depth-r2-v1') { $config.controlnet }
        else { Join-Path (Split-Path $modelPath) 'control_v11p_sd15_openpose.pth' }
}
if (-not $OpenPoseConfig) {
    $OpenPoseConfig = if ($config.openpose.controlnetConfig) { $config.openpose.controlnetConfig }
        elseif ($config.poseEstimator -ne 'paired-depth-r2-v1') { $config.controlnetConfig }
        else { Join-Path $DreamRoot 'models/hq/openpose-controlnet' }
}
$skeletonPath = (Resolve-Path -LiteralPath $OpenPoseModel).Path
$skeletonConfig = (Resolve-Path -LiteralPath $OpenPoseConfig).Path
function Assert-DreamHash([string]$File, [string]$Expected) {
    if ((Get-FileHash -LiteralPath $File -Algorithm SHA256).Hash -ne $Expected) {
        throw "HQ checksum mismatch: $File"
    }
}
Assert-DreamHash $modelPath '761077ffe369fe8cf16ae353f8226bd4ca29805b161052f82c0170c7b50f1d99'
Assert-DreamHash $skeletonPath 'db97becd92cd19aff71352a60e93c2508decba3dee64f01f686727b9b406a9dd'
Assert-DreamHash (Join-Path $skeletonConfig 'config.json') 'aa6fecc8745c0d0b26f0d2ca0f686600c8b33177c667d44eb41a51e56e44a697'
$modelConfig = Join-Path $pack 'controlnet'
Assert-DreamHash (Join-Path $modelConfig 'config.json') 'ee789f6b46cd8c443c80ffb81e5c05e14b8b3cbec9e861829bfa3d2a6d3ee16f'
$manifest = Get-Content -LiteralPath (Join-Path $pack 'manifest.json') -Raw | ConvertFrom-Json
foreach ($item in $manifest.items) {
    if ($item.depthSha256 -cnotmatch '^[0-9a-f]{64}$') { throw 'Invalid depth digest' }
    Assert-DreamHash (Join-Path $pack ($item.depthSha256+'.webp')) $item.depthSha256
}
if ($config.openpose.controlnet -eq $skeletonPath -and $config.openpose.controlnetConfig -eq $skeletonConfig -and
    $config.poseEstimator -eq $manifest.poseEstimator -and $config.controlnet -eq $modelPath -and
    $config.controlnetConfig -eq $modelConfig -and $config.poseScale -eq .9 -and $config.garmentScale -eq .7 -and $config.offload -eq 'sequential') {
    Write-Output 'HQ paired depth already enabled'
    return
}
$config.controlnet = $modelPath
$config.openpose = @{controlnet=$skeletonPath; controlnetConfig=$skeletonConfig}
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
Write-Output "HQ full catalog enabled with OpenPose and $($manifest.items.Count) paired depth poses. Previous config: $backup"
