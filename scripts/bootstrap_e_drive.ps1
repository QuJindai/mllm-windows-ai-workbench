param(
  [string]$Root = "E:\Dream"
)

$ErrorActionPreference = "Stop"
$Root = [IO.Path]::GetFullPath($Root)

if (-not $Root.StartsWith("E:\", [StringComparison]::OrdinalIgnoreCase)) {
  throw "Dream root must be on E:; received $Root"
}

$Dirs = @(
  "$Root\app",
  "$Root\app\current",
  "$Root\app\versions",
  "$Root\app\runtime",
  "$Root\src",
  "$Root\models",
  "$Root\models\source",
  "$Root\models\windows",
  "$Root\models\windows\gguf",
  "$Root\models\windows\quantized",
  "$Root\models\windows\manifests",
  "$Root\models\research",
  "$Root\cache",
  "$Root\cache\huggingface",
  "$Root\cache\huggingface\hub",
  "$Root\cache\torch",
  "$Root\cache\diffusers",
  "$Root\cache\transformers",
  "$Root\cache\cuda",
  "$Root\cache\cmake",
  "$Root\cache\cargo",
  "$Root\cache\npm",
  "$Root\cache\nuget",
  "$Root\cache\build",
  "$Root\env",
  "$Root\env\python",
  "$Root\env\venv",
  "$Root\env\node",
  "$Root\env\rust",
  "$Root\env\tools",
  "$Root\data",
  "$Root\data\history",
  "$Root\data\favorites",
  "$Root\data\thumbnails",
  "$Root\data\metadata",
  "$Root\experiments",
  "$Root\experiments\fusion",
  "$Root\experiments\steps",
  "$Root\experiments\model_compare",
  "$Root\experiments\attention",
  "$Root\traces",
  "$Root\traces\runtime",
  "$Root\traces\latent",
  "$Root\traces\influence",
  "$Root\traces\attention",
  "$Root\exports",
  "$Root\logs",
  "$Root\temp",
  "$Root\builds",
  "$Root\builds\debug",
  "$Root\builds\release",
  "$Root\builds\installer",
  "$Root\backups",
  "$Root\ci",
  "$Root\ci\runner",
  "$Root\ci\work",
  "$Root\ci\cache"
)

foreach ($Dir in $Dirs) {
  New-Item -ItemType Directory -Force -Path $Dir | Out-Null
}

Write-Host "E_DRIVE_LAYOUT_PASS"
Write-Host "Dream root: $Root"

