$ErrorActionPreference='Stop'
Set-StrictMode -Version 2
$Root=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
function Assert-True([bool]$Condition,[string]$Message){ if(-not $Condition){ throw $Message } }
Write-Host "PS_EDITION=$($PSVersionTable.PSEdition)"
Write-Host "PS_VERSION=$($PSVersionTable.PSVersion)"
Assert-True ($PSVersionTable.PSVersion.Major -eq 5) 'This smoke test must execute under Windows PowerShell 5.1.'
$parseErrors=@()
Get-ChildItem -LiteralPath $Root -Recurse -Include *.ps1,*.psm1 -File | Where-Object { $_.FullName -notmatch '[\\/]dist[\\/]' } | ForEach-Object {
    $tokens=$null;$errs=$null
    [void][System.Management.Automation.Language.Parser]::ParseFile($_.FullName,[ref]$tokens,[ref]$errs)
    foreach($e in @($errs)){ $parseErrors += "$($_.FullName): $($e.Message)" }
}
Assert-True ($parseErrors.Count -eq 0) ("PS5.1 parse failures:`n"+($parseErrors -join "`n"))
foreach($m in @('Core','State','Detection','Network','Download','Security','Evidence','Runtime')){Import-Module (Join-Path $Root "engine\$m.psm1") -Force -ErrorAction Stop}
$cfg=Get-MLLMConfig -ProjectRoot $Root
Assert-True ($null -ne $cfg) 'Get-MLLMConfig returned null.'
Import-MLLMTasks -ProjectRoot $Root
$tasks=@(Get-MLLMRegisteredTasks)
Assert-True ($tasks.Count -gt 0) 'No tasks registered.'
[xml]$xaml=Get-Content -LiteralPath (Join-Path $Root 'gui\Workbench.xaml') -Raw -Encoding UTF8
Assert-True ($null -ne $xaml) 'XAML parse failed.'
Write-Host 'WINDOWS_PS51_SMOKE=PASS'
