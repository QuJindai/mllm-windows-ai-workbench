import json
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "config" / "dream" / "model-registry.json"
VALIDATOR = ROOT / "scripts" / "validate_model_registry.ps1"
GUIDE = ROOT / "docs" / "dream-windows" / "W1_MODEL_IMPORT.md"


def test_registry_and_validator_exist():
    assert REGISTRY.is_file()
    assert VALIDATOR.is_file()
    assert GUIDE.is_file()


def test_first_model_declares_truthful_cyberrealistic_standard_identity():
    data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    assert data["first_model_id"] == "cyberrealistic-xl-v10-standard"
    model = next(item for item in data["models"] if item["model_id"] == data["first_model_id"])
    assert model["display_name"] == "CyberRealistic XL v10（标准版）"
    assert model["architecture"] == "SDXL"
    assert model["dmd2"]["enabled"] is False
    assert model["aliases"] == ["cyberrealistic-v10-dmd2"]
    assert model["status"] == "installed"


def test_windows_identity_is_gguf_and_e_drive_only():
    data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    model = data["models"][0]
    windows = model["windows"]
    assert windows["format"] == "gguf"
    assert windows["path"].lower().startswith("e:\\dream\\")
    assert windows["path"].lower().endswith(".gguf")
    assert ".bin" not in windows["path"].lower()
    sha256 = windows["sha256"]
    assert re.fullmatch(r"[0-9a-f]{64}", sha256, re.IGNORECASE)
    assert sha256.lower() == "48a2d2a0faa6332b3d8718707fedba750c75854904389c134b9535e23b1639f6"
    assert model["source"]["provider"] == "Civitai"
    assert model["source"]["version_id"] == 2840768
    assert model["source"]["sha256"].lower() == "fd5e870b5bbce4bddeb64f4bb8e49c57f84ab793c0262a503f0123be435e667d"
    assert model["source"]["expected_sha256"].lower() == "fd5e870b5bbce4bddeb64f4bb8e49c57f84ab793c0262a503f0123be435e667d"


def test_android_reference_is_provenance_only():
    data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    ref = data["models"][0]["android_reference"]
    assert ref["branch"] == "feature/s24u-image-harness-h6r5-semantic-fidelity"
    assert ref["commit"] == "381713f6985e1d48da16a14636989a4b27f1ae98"
    assert ref["artifact_policy"] == "reference-only"


def test_validator_has_fail_closed_markers_and_accepts_uninstalled_registry():
    text = VALIDATOR.read_text(encoding="utf-8")
    for marker in (
        "MODEL_REGISTRY_PASS",
        "MODEL_REGISTRY_FAIL",
        "sha256",
        "uninstalled",
        "E:\\Dream",
        "unet.bin",
    ):
        assert marker in text
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(VALIDATOR), "-Root", "E:\\Dream"],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "MODEL_REGISTRY_PASS" in result.stdout
