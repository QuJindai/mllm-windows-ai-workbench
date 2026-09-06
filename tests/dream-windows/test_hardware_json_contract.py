import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
TEMPLATE = ROOT / "templates" / "dream-hardware.template.json"


def test_hardware_scripts_exist():
    for name in (
        "collect_hardware.ps1",
        "verify_cuda.ps1",
        "verify_no_c_drive_assets.ps1",
    ):
        assert (SCRIPTS / name).is_file(), name


def test_hardware_probe_contract_is_truthful_and_e_drive_only():
    text = (SCRIPTS / "collect_hardware.ps1").read_text(encoding="utf-8")
    for marker in ("HARDWARE_PROBE_PASS", "CUDA_VISIBLE_PASS", "nvidia-smi", "hardware.json"):
        assert marker in text, marker
    for field in (
        "timestamp",
        "os",
        "cpu",
        "ram",
        "nvidia",
        "e_drive",
        "memory_total_mib",
        "driver_version",
        "free_bytes",
    ):
        assert field in text, field
    assert "C:\\" not in text


def test_cuda_and_no_c_drive_scripts_fail_closed():
    cuda = (SCRIPTS / "verify_cuda.ps1").read_text(encoding="utf-8")
    no_c = (SCRIPTS / "verify_no_c_drive_assets.ps1").read_text(encoding="utf-8")
    assert "CUDA_VISIBLE_FAIL" in cuda
    assert "CUDA_VISIBLE_PASS" in cuda
    assert "NO_C_DRIVE_DREAM_ASSET_FAIL" in no_c
    assert "NO_C_DRIVE_DREAM_ASSET_PASS" in no_c
    assert "DREAM_HOME" in no_c


def test_hardware_template_declares_local_baseline():
    data = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    assert data["gpu"] == "NVIDIA RTX 1000 Ada Laptop GPU"
    assert data["vram_gb"] == 6
    assert data["ram_gb"] == 64
    assert data["dream_root"] == "E:\\Dream"

