from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FIXED_ZIP_TIME = (2020, 1, 1, 0, 0, 0)

FOUNDATION_ROOT_FILES = [
    "Start_M_LLM_Workbench.ps1",
    "Bootstrap_SafeCore.ps1",
    "M_LLM_PHYSICAL_PREFLIGHT.ps1",
    "M_LLM_GUI_PREFLIGHT.ps1",
]
FOUNDATION_DIRS = ["engine", "gui", "config", "web"]
SEED_INSTALLER_SUFFIXES = {".ps1", ".psm1", ".xaml"}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def add_bytes(zf: zipfile.ZipFile, arcname: str, data: bytes) -> None:
    info = zipfile.ZipInfo(arcname.replace("\\", "/"), FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    zf.writestr(info, data)


def build_zip(entries: list[tuple[str, bytes]]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for arcname, data in sorted(entries, key=lambda x: x[0].lower()):
            add_bytes(zf, arcname, data)
    return buf.getvalue()


def foundation_entries() -> list[tuple[str, bytes]]:
    entries: list[tuple[str, bytes]] = []
    for relative in FOUNDATION_ROOT_FILES:
        path = ROOT / relative
        if not path.is_file():
            raise SystemExit(f"materialized foundation file missing: {relative}")
        entries.append((relative, path.read_bytes()))
    for dirname in FOUNDATION_DIRS:
        base = ROOT / dirname
        if not base.is_dir():
            raise SystemExit(f"materialized foundation directory missing: {dirname}")
        for path in sorted(p for p in base.rglob("*") if p.is_file()):
            entries.append((path.relative_to(ROOT).as_posix(), path.read_bytes()))
    return entries


def installer_entries() -> list[tuple[str, bytes]]:
    base = ROOT / "installer"
    if not base.is_dir():
        raise SystemExit("installer directory missing")
    entries: list[tuple[str, bytes]] = []
    for path in sorted(p for p in base.rglob("*") if p.is_file()):
        if path.suffix.lower() not in SEED_INSTALLER_SUFFIXES:
            continue
        entries.append((path.relative_to(ROOT).as_posix(), path.read_bytes()))
    required = {
        "installer/Start-UniversalInstaller.ps1",
        "installer/InstallerPaths.psm1",
        "installer/InstallerState.psm1",
        "installer/Acquisition.psm1",
        "installer/PackageValidation.psm1",
        "installer/Activation.psm1",
        "installer/InstallerEvidence.psm1",
        "installer/InstallerEngine.psm1",
        "installer/UniversalInstaller.Wpf.ps1",
        "installer/UniversalInstaller.xaml",
    }
    present = {name for name, _ in entries}
    missing = sorted(required - present)
    if missing:
        raise SystemExit("seed installer files missing: " + ", ".join(missing))
    return entries


def powershell_bootstrap() -> str:
    return r"""$ErrorActionPreference='Stop'
$self=$env:MLLM_SEED_SELF
$smoke=($env:MLLM_SEED_SMOKE -eq '1')
$version=$env:MLLM_SEED_VERSION
$foundationVersion=$env:MLLM_FOUNDATION_VERSION
$expected=$env:MLLM_SEED_PAYLOAD_SHA256
if(-not(Test-Path -LiteralPath $self -PathType Leaf)){throw 'Seed self path missing'}
$content=[IO.File]::ReadAllText($self,[Text.Encoding]::ASCII)
$marker='__MLLM_SEED_PAYLOAD__'
$pos=$content.LastIndexOf($marker,[StringComparison]::Ordinal)
if($pos -lt 0){throw 'Seed payload marker missing'}
$b64=($content.Substring($pos+$marker.Length) -replace '[^A-Za-z0-9+/=]','')
[byte[]]$payload=[Convert]::FromBase64String($b64)
$sha=([BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash($payload))).Replace('-','').ToLowerInvariant()
if($sha -ne $expected){throw ('Seed payload SHA256 mismatch expected='+$expected+' actual='+$sha)}
Write-Host ('UNIVERSAL_SEED_PAYLOAD=PASS sha256='+$sha)
$base=if($smoke){Join-Path $env:TEMP 'M_LLM_UNIVERSAL_SEED_SMOKE'}else{Join-Path $env:ProgramData 'M-LLM\Installer\seed'}
if(-not(Test-Path -LiteralPath $base -PathType Container)){New-Item -ItemType Directory -Force -Path $base|Out-Null}
$root=Join-Path $base $version
if($smoke -and (Test-Path -LiteralPath $root)){Remove-Item -LiteralPath $root -Recurse -Force}
$valid=$false
if(Test-Path -LiteralPath $root -PathType Container){
  $stamp=Join-Path $root '.seed_payload_sha256'
  $entry=Join-Path $root 'installer\Start-UniversalInstaller.ps1'
  if((Test-Path -LiteralPath $stamp -PathType Leaf) -and (Test-Path -LiteralPath $entry -PathType Leaf)){$valid=((Get-Content -LiteralPath $stamp -Raw).Trim() -eq $expected)}
}
if(-not $valid){
  $target=$root
  if(Test-Path -LiteralPath $target){$target=$root+'.repair.'+([guid]::NewGuid().ToString('N').Substring(0,8))}
  New-Item -ItemType Directory -Force -Path $target|Out-Null
  $zip=Join-Path ([IO.Path]::GetTempPath()) ('mllm-seed-'+[guid]::NewGuid().ToString('N')+'.zip')
  try{[IO.File]::WriteAllBytes($zip,$payload);Expand-Archive -LiteralPath $zip -DestinationPath $target -Force}finally{Remove-Item -LiteralPath $zip -Force -ErrorAction SilentlyContinue}
  [IO.File]::WriteAllText((Join-Path $target '.seed_payload_sha256'),$expected,(New-Object Text.UTF8Encoding($false)))
  $root=$target
}
$manifest=Join-Path $root 'config\source-manifest.json'
$foundation=Join-Path $root 'packages\workbench-foundation.zip'
$entry=Join-Path $root 'installer\Start-UniversalInstaller.ps1'
foreach($p in @($manifest,$foundation,$entry)){if(-not(Test-Path -LiteralPath $p -PathType Leaf)){throw ('Seed extracted file missing: '+$p)}}
$m=Get-Content -LiteralPath $manifest -Raw -Encoding UTF8|ConvertFrom-Json
$pkg=@($m.packages|Where-Object {$_.role -eq 'workbench-foundation'}|Select-Object -First 1)
if($pkg.Count -ne 1){throw 'Seed workbench-foundation manifest entry missing'}
$fsha=(Get-FileHash -LiteralPath $foundation -Algorithm SHA256).Hash.ToLowerInvariant()
if($fsha -ne ([string]$pkg[0].sha256).ToLowerInvariant()){throw 'Embedded foundation SHA256 mismatch'}
$pkg[0].sources[0].path=$foundation
$m|ConvertTo-Json -Depth 20|Set-Content -LiteralPath $manifest -Encoding UTF8
Write-Host ('UNIVERSAL_SEED_FOUNDATION=PASS sha256='+$fsha)
Write-Host ('UNIVERSAL_SEED_ROOT='+$root)
if($smoke){
  & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $entry -VersionId $foundationVersion -SourceManifestPath $manifest -NoElevate -PathsOnly -NoGui
  if($LASTEXITCODE -ne 0){exit $LASTEXITCODE}
  Write-Host 'UNIVERSAL_SEED_SMOKE=PASS'
  exit 0
}
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $entry -VersionId $foundationVersion -SourceManifestPath $manifest
exit $LASTEXITCODE
"""


def build_seed(output: Path, version: str) -> dict[str, str | int]:
    foundation = build_zip(foundation_entries())
    foundation_sha = sha256(foundation)
    foundation_version = f"foundation-{version}"
    runtime_manifest = {
        "schema": "mllm.universal-installer.sources.v1",
        "provider_kinds": ["local_file", "local_cache", "http", "github", "custom_proxy"],
        "policy": {
            "prefer_local_before_network": True,
            "verify_sha256_before_use": True,
            "continue_after_source_failure": True,
            "allow_unverified_mirror": False,
        },
        "packages": [
            {
                "id": "workbench-foundation",
                "role": "workbench-foundation",
                "version": foundation_version,
                "file_name": "workbench-foundation.zip",
                "sha256": foundation_sha,
                "sources": [
                    {
                        "id": "embedded-foundation",
                        "kind": "local_file",
                        "path": "__SEED_BOOTSTRAP_REWRITES_ABSOLUTE_PATH__",
                    }
                ],
            }
        ],
    }
    seed_entries = installer_entries()
    seed_entries += [
        ("config/source-manifest.json", (json.dumps(runtime_manifest, indent=2) + "\n").encode("utf-8")),
        ("packages/workbench-foundation.zip", foundation),
    ]
    payload = build_zip(seed_entries)
    payload_sha = sha256(payload)
    bootstrap_b64 = base64.b64encode(powershell_bootstrap().encode("utf-8")).decode("ascii")
    payload_b64 = base64.b64encode(payload).decode("ascii")
    bootstrap_lines = "\r\n".join(bootstrap_b64[i : i + 76] for i in range(0, len(bootstrap_b64), 76))
    payload_lines = "\r\n".join(payload_b64[i : i + 76] for i in range(0, len(payload_b64), 76))
    bootstrap_reader = (
        "$c=[IO.File]::ReadAllText($env:MLLM_SEED_SELF,[Text.Encoding]::ASCII);"
        "$m='__MLLM_SEED_BOOTSTRAP__';$p='__MLLM_SEED_PAYLOAD__';"
        "$a=$c.LastIndexOf($m);$b=$c.LastIndexOf($p);if($a -lt 0 -or $b -le $a){exit 90};"
        "$x=($c.Substring($a+$m.Length,$b-$a-$m.Length) -replace '\\s','');"
        "iex ([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($x)))"
    )
    header = f"""@echo off\r
setlocal EnableExtensions\r
title M-LLM Universal Installer - Single File\r
set "MLLM_SEED_SELF=%~f0"\r
set "MLLM_SEED_VERSION={version}"\r
set "MLLM_FOUNDATION_VERSION={foundation_version}"\r
set "MLLM_SEED_PAYLOAD_SHA256={payload_sha}"\r
set "MLLM_SEED_SMOKE=0"\r
if /I "%~1"=="--seed-smoke" set "MLLM_SEED_SMOKE=1"\r
if "%MLLM_SEED_SMOKE%"=="1" goto seed_run\r
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "if(([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){{exit 0}}else{{exit 1}}"\r
if not errorlevel 1 goto seed_run\r
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath $env:MLLM_SEED_SELF -Verb RunAs"\r
exit /b %ERRORLEVEL%\r
:seed_run\r
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "{bootstrap_reader}"\r
set "MLLM_RC=%ERRORLEVEL%"\r
if not "%MLLM_RC%"=="0" if not "%MLLM_SEED_SMOKE%"=="1" (\r
  echo.\r
  echo [ERROR] M-LLM Universal Installer failed with RC=%MLLM_RC%\r
  echo Press any key to close.\r
  pause ^>nul\r
)\r
exit /b %MLLM_RC%\r
__MLLM_SEED_BOOTSTRAP__\r
"""
    data = (header + bootstrap_lines + "\r\n__MLLM_SEED_PAYLOAD__\r\n" + payload_lines + "\r\n").encode("ascii")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(data)
    return {
        "output": str(output),
        "bytes": len(data),
        "sha256": sha256(data),
        "seed_payload_sha256": payload_sha,
        "foundation_sha256": foundation_sha,
        "version": version,
        "foundation_version": foundation_version,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="dist/M_LLM_UNIVERSAL_INSTALLER_FULL.cmd")
    parser.add_argument("--version", default="")
    args = parser.parse_args()
    sha = os.environ.get("GITHUB_SHA", "")
    version = args.version or ("phase1-" + (sha[:12] if sha else "local"))
    output = Path(args.output)
    if not output.is_absolute():
        output = (ROOT / output).resolve()
    report = build_seed(output, version)
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
