import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
CORE = ROOT / "dream" / "core"
MAIN = CORE / "src" / "main.cpp"
CMAKE = CORE / "CMakeLists.txt"
PREPARE = ROOT / "scripts" / "prepare_dream_core.ps1"
PREFLIGHT = ROOT / "tests" / "dream-windows" / "Invoke-DreamW1Preflight.ps1"


def test_native_core_boundary_files_exist():
    for path in (MAIN, CMAKE, PREPARE, PREFLIGHT):
        assert path.is_file(), path


def test_native_core_has_truthful_cli_and_storage_guards():
    text = MAIN.read_text(encoding="utf-8")
    for marker in (
        "stable-diffusion.cpp",
        "CUDA",
        "--version",
        "hardware",
        "generate",
        "DREAM_DEPENDENCY_MISSING",
        "MODEL_UNINSTALLED",
        "E:\\\\Dream",
        "metadata",
    ):
        assert marker in text, marker
    assert "placeholder" not in text.lower()
    assert re.search(r"IsUnderRoot|under.*root", text, re.IGNORECASE)


def test_preflight_is_fail_closed_and_persisted_on_e_drive():
    text = PREPARE.read_text(encoding="utf-8") + PREFLIGHT.read_text(encoding="utf-8")
    for marker in (
        "W1_PREFLIGHT_PASS",
        "W1_PREFLIGHT_BLOCKED",
        "STABLE_DIFFUSION_CPP_MISSING",
        "CYBERREALISTIC_MODEL_MISSING",
        "preflight.json",
        "E:\\Dream",
    ):
        assert marker in text, marker
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(PREFLIGHT),
            "-Root",
            "E:\\Dream",
            "-RepoRoot",
            str(ROOT),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    assert "W1_PREFLIGHT_BLOCKED" in result.stdout
