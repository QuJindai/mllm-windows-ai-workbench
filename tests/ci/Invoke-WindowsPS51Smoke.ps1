$ErrorActionPreference='Stop'
Set-StrictMode -Version 2
$Root=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
function Assert-True([bool]$Condition,[string]$Message){ if(-not $Condition){ throw $Message } }
Write-Host "PS_EDITION=$($PSVersionTable.PSEdition)"
Write-Host "PS_VERSION=$($PSVersionTable.PSVersion)"
Assert-True ($PSVersionTable.PSVersion.Major -eq 5) 'This smoke test must execute under Windows PowerShell 5.1.'
& (Join-Path $Root 'ci\Test-PowerShellSource.ps1') -SourceRoot $Root -RuntimeGroup Legacy51
foreach($m in @('Core','State','Detection','Network','Download','Security','Evidence','Runtime')){Import-Module (Join-Path $Root "engine\$m.psm1") -Force -ErrorAction Stop}
$cfg=Get-MLLMConfig -ProjectRoot $Root
Assert-True ($null -ne $cfg) 'Get-MLLMConfig returned null.'
Import-MLLMTasks -ProjectRoot $Root
$tasks=@(Get-MLLMRegisteredTasks)
Assert-True ($tasks.Count -gt 0) 'No tasks registered.'
[xml]$xaml=Get-Content -LiteralPath (Join-Path $Root 'gui\Workbench.xaml') -Raw -Encoding UTF8
Assert-True ($null -ne $xaml) 'XAML parse failed.'
Write-Host 'WINDOWS_PS51_SMOKE=PASS'
