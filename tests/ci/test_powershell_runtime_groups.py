"""Exercise the real parse gate under both installed Windows PowerShell hosts."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]
CHECKER = ROOT / "ci" / "Test-PowerShellSource.ps1"
HOSTS = {"Legacy51": shutil.which("powershell.exe"), "PowerShell7": shutil.which("pwsh.exe")}
pytestmark = pytest.mark.skipif(
    os.name != "nt" or not all(HOSTS.values()), reason="requires both Windows PowerShell hosts"
)


@pytest.fixture
def source_tree(tmp_path):
    (tmp_path / "ci").mkdir()
    (tmp_path / "scripts").mkdir()
    # A parse gate must never run/import the source it checks.
    (tmp_path / "legacy.ps1").write_text("throw 'SOURCE_MUST_NOT_EXECUTE'\n", encoding="ascii")
    (tmp_path / "scripts" / "dream.ps1").write_text(
        "#Requires -Version 7.0\n$x = $null ?? '磁盘低于'\nthrow 'SOURCE_MUST_NOT_EXECUTE'\n",
        encoding="utf-8",
    )
    set_manifest(tmp_path, ["scripts/dream.ps1"])
    return tmp_path


def set_manifest(root, paths):
    (root / "ci" / "powershell-runtimes.json").write_text(
        json.dumps({"schemaVersion": 1, "powershell7": paths}), encoding="utf-8"
    )


def run_gate(root, group, host=None):
    return subprocess.run(
        [HOSTS[host or group], "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(CHECKER),
         "-SourceRoot", str(root), "-RuntimeGroup", group],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
    )


@pytest.mark.parametrize("group,checked,other", [
    ("Legacy51", ["legacy.ps1"], ["scripts/dream.ps1"]),
    ("PowerShell7", ["legacy.ps1", "scripts/dream.ps1"], []),
])
def test_modern_scripts_use_ps7_and_shared_sources_keep_both_checks(source_tree, group, checked, other):
    result = run_gate(source_tree, group)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["checkedFiles"] == checked
    assert report["otherRuntimeFiles"] == other
    assert report["runtimeGroup"] == group


@pytest.mark.parametrize("group,path", [("Legacy51", "legacy.ps1"), ("PowerShell7", "scripts/dream.ps1")])
def test_syntax_errors_in_either_group_fail_the_gate(source_tree, group, path):
    (source_tree / path).write_text("function Broken {\n", encoding="ascii")
    result = run_gate(source_tree, group)
    assert result.returncode != 0
    assert "POWERSHELL_SOURCE_PARSE_FAILED" in result.stdout + result.stderr
    assert path in result.stdout + result.stderr


def test_new_unlisted_scripts_still_receive_legacy_validation(source_tree):
    (source_tree / "scripts" / "new.psm1").write_text("function Broken {\n", encoding="ascii")
    result = run_gate(source_tree, "Legacy51")
    assert result.returncode != 0
    assert "scripts/new.psm1" in result.stdout + result.stderr


@pytest.mark.parametrize("group,host", [("Legacy51", "PowerShell7"), ("PowerShell7", "Legacy51")])
def test_wrong_host_cannot_claim_runtime_coverage(source_tree, group, host):
    result = run_gate(source_tree, group, host)
    assert result.returncode != 0
    assert "POWERSHELL_RUNTIME_MISMATCH" in result.stdout + result.stderr


@pytest.mark.parametrize("group", ["Legacy51", "PowerShell7"])
def test_default_source_root_works_without_explicit_argument(source_tree, group):
    checker = source_tree / "ci" / CHECKER.name
    shutil.copyfile(CHECKER, checker)
    result = subprocess.run(
        [HOSTS[group], "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(checker),
         "-RuntimeGroup", group], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ci/Test-PowerShellSource.ps1" in json.loads(result.stdout)["checkedFiles"]


@pytest.mark.parametrize("paths", [
    [], ["scripts/missing.ps1"], ["scripts/*.ps1"], ["../outside.ps1"],
    ["/scripts/dream.ps1"], ["C:/scripts/dream.ps1"], ["scripts/dream.ps1", "scripts/DREAM.ps1"],
    "scripts/dream.ps1", ["scripts/dream.ps1", "ci/powershell-runtimes.json"],
])
def test_invalid_or_stale_manifests_fail_instead_of_silently_skipping(source_tree, paths):
    set_manifest(source_tree, paths)
    result = run_gate(source_tree, "Legacy51")
    assert result.returncode != 0
    assert "POWERSHELL_RUNTIME_MANIFEST_INVALID" in result.stdout + result.stderr


@pytest.mark.parametrize("group", ["Legacy51", "PowerShell7"])
@pytest.mark.parametrize("version", [None, True, "1", 1.0, [], [1], {}])
def test_manifest_version_must_be_an_integer_scalar(source_tree, group, version):
    (source_tree / "ci/powershell-runtimes.json").write_text(
        json.dumps({"schemaVersion": version, "powershell7": ["scripts/dream.ps1"]}), encoding="utf-8"
    )
    result = run_gate(source_tree, group)
    assert result.returncode != 0
    assert "POWERSHELL_RUNTIME_MANIFEST_INVALID" in result.stdout + result.stderr


def test_legacy_encoding_errors_remain_detectable(source_tree):
    probe = subprocess.run(
        [HOSTS["Legacy51"], "-NoProfile", "-Command", "[Text.Encoding]::Default.CodePage"],
        capture_output=True, text=True, timeout=30, check=True,
    )
    codepage = int(probe.stdout.strip())
    samples = {936: "无法将.+识别为", 1252: "我"}
    if codepage not in samples:
        pytest.skip(f"ANSI regression fixture covers CP936/1252; actual CP{codepage}")
    # Raw UTF-8 without a BOM is valid in PS7, but the real PS5.1 ANSI reader
    # misdecodes the closing quote (936) or creates a smart quote (1252).
    (source_tree / "legacy.ps1").write_text(f"$x='{samples[codepage]}'\n", encoding="utf-8")
    modern = run_gate(source_tree, "PowerShell7")
    assert modern.returncode == 0, modern.stdout + modern.stderr
    result = run_gate(source_tree, "Legacy51")
    assert result.returncode != 0
    assert "POWERSHELL_SOURCE_PARSE_FAILED" in result.stdout + result.stderr


def test_dist_exclusion_does_not_drop_similarly_named_source(source_tree):
    (source_tree / "dist").mkdir()
    (source_tree / "dist" / "generated.ps1").write_text("function Broken {", encoding="ascii")
    (source_tree / "distribution").mkdir()
    (source_tree / "distribution" / "source.ps1").write_text("'still checked'", encoding="ascii")
    result = run_gate(source_tree, "Legacy51")
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["checkedFiles"] == ["distribution/source.ps1", "legacy.ps1"]


@pytest.mark.parametrize("codepage", [936, 1252])
def test_gui_snapshot_legacy_source_decodes_on_chinese_and_english_windows(tmp_path, codepage):
    # Match Windows PowerShell's BOM detection with either OS ANSI fallback.
    # Only parse the real file; the GUI entrypoint must not run during this test.
    probe = tmp_path / "check-legacy-encoding.ps1"
    probe.write_text("""param([string]$SourceFile, [int]$CodePage)
$ErrorActionPreference = 'Stop'
$reader = New-Object System.IO.StreamReader($SourceFile, [Text.Encoding]::GetEncoding($CodePage), $true)
try { $source = $reader.ReadToEnd() } finally { $reader.Dispose() }
$tokens = $null
$parseErrors = $null
$null = [Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count -gt 0) { throw ($parseErrors.Message -join '; ') }
""", encoding="ascii")
    result = subprocess.run(
        [HOSTS["Legacy51"], "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(probe),
         "-SourceFile", str(ROOT / "tests/ci/Invoke-GuiSnapshotSmoke.ps1"), "-CodePage", str(codepage)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
