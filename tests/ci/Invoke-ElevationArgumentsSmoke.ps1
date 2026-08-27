[CmdletBinding()]
param()
$ErrorActionPreference='Stop'
Set-StrictMode -Version 2

$Root=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$module=Join-Path $Root 'installer\InstallerPaths.psm1'
Import-Module $module -Force -ErrorAction Stop

if($null -eq (Get-Command New-MLLMElevationArguments -ErrorAction SilentlyContinue)){throw 'New-MLLMElevationArguments is missing'}

$entry='C:\Program Files\M-LLM\Installer Root\Start-UniversalInstaller.ps1'
$runId='run id 42'
$original=@('-VersionId','v 1 release','-SourceManifestPath','C:\Offline Packages\source manifest.json','-NoGui','-GuiSmoke')
$result=New-MLLMElevationArguments -EntryPath $entry -RunId $runId -OriginalArgs $original
$args=@($result.ArgumentList)
if($args.Count -ne 5){throw "Unexpected elevation argument count: $($args.Count)"}
if($args[0] -ne '-NoProfile' -or $args[1] -ne '-ExecutionPolicy' -or $args[2] -ne 'Bypass' -or $args[3] -ne '-EncodedCommand'){throw "Unexpected elevation fixed arguments: $($args -join '|')"}
if([string]::IsNullOrWhiteSpace([string]$args[4])){throw 'EncodedCommand payload is empty'}

$decoded=[Text.Encoding]::Unicode.GetString([Convert]::FromBase64String([string]$args[4]))
$m=[regex]::Match($decoded,"\$payload='([A-Za-z0-9+/=]+)'")
if(-not $m.Success){throw "Encoded elevation script does not contain payload: $decoded"}
$json=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($m.Groups[1].Value))
$obj=$json | ConvertFrom-Json
if([string]$obj.entry -ne $entry){throw "Entry path changed across elevation: $($obj.entry)"}
if([string]$obj.run_id -ne $runId){throw "RunId changed across elevation: $($obj.run_id)"}
$round=@($obj.args)
if($round.Count -ne $original.Count){throw "Forwarded argument count changed: $($round.Count)"}
for($i=0;$i -lt $original.Count;$i++){
    if([string]$round[$i] -ne [string]$original[$i]){throw "Forwarded argument changed at index $i expected=[$($original[$i])] actual=[$($round[$i])]"}
}
if($decoded -notmatch [regex]::Escape('& ([string]$o.entry) @forward')){throw 'Encoded elevation script does not invoke entrypoint with splatted argument array'}
Write-Host 'UNIVERSAL_ELEVATION_ARGUMENTS=PASS spaces=true switches=true'
