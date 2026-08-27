[CmdletBinding()]
param()
$ErrorActionPreference='Stop'
Set-StrictMode -Version 2
$root=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$backend=Join-Path $root 'runtime\WorkbenchBackend.ps1'
if(-not(Test-Path -LiteralPath $backend -PathType Leaf)){throw "WorkbenchBackend.ps1 missing: $backend"}
$content=Get-Content -LiteralPath $backend -Raw
if($content -notmatch "ProtocolVersion.+1\.0"){throw 'Protocol 1.0 validation missing'}
$match=[regex]::Match($content,'(?s)\$MethodTable\s*=\s*@\{(?<body>.*?)\n\}')
if(-not $match.Success){throw 'MethodTable allowlist not found'}
$keys=@([regex]::Matches($match.Groups['body'].Value,"(?m)^\s*'([^']+)'\s*=") | ForEach-Object { $_.Groups[1].Value })
if($keys -notcontains 'system.ping'){throw 'system.ping allowlist method missing'}
$forbidden=@($keys | Where-Object { $_ -match '(?i)exec|command|script|eval|shell|powershell' })
if($forbidden.Count -gt 0){throw ('Forbidden backend method exposed: '+($forbidden -join ','))}
Write-Host ('WORKBENCH_BACKEND_CONTRACT=PASS methods='+($keys -join ','))
