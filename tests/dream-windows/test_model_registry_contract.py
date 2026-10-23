import json
import re
import subprocess
import tempfile
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


def test_animagine_windows_model_has_verified_identity_and_quality_profile():
    data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    model = next(item for item in data["models"] if item["model_id"] == "animagine-xl-4.0-opt-standard")
    assert model["display_name"] == "Animagine XL 4.0 Opt（动漫）"
    assert model["architecture"] == "SDXL"
    assert model["status"] == "installed"
    assert model["dmd2"]["enabled"] is False
    assert "android_reference" not in model
    assert model["source"]["repo_id"] == "cagliostrolab/animagine-xl-4.0"
    assert model["source"]["revision"] == "2b7c1b397761bf5bd3cc42e5b39ec99314a75a96"
    assert model["source"]["expected_sha256"] == "6327eca98bfb6538dd7a4edce22484a1bbc57a8cff6b11d075d40da1afb847ac"
    assert model["windows"]["sha256"] == "d8a087e5453cd5d394e24fad17980044b11a59460a17b5dd0edd078634b2698e"
    assert model["generation_defaults"] == {
        "width": 768,
        "height": 768,
        "steps": 28,
        "cfg": 5.0,
        "sampling_method": "euler_a",
        "scheduler": "discrete",
    }


def test_dreamshaper_lightning_has_verified_identity_and_audited_local_profile():
    data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    model = next(item for item in data["models"] if item["model_id"] == "dreamshaper-xl-lightning")
    assert model["display_name"] == "DreamShaper XL Lightning（通用创意）"
    assert model["architecture"] == "SDXL"
    assert model["status"] == "installed"
    assert model["dmd2"]["enabled"] is False
    assert model["dmd2"]["variant"] == "lightning"
    assert model["dmd2"]["steps_default"] == 8
    assert "android_reference" not in model
    assert model["source"]["repo_id"] == "Lykon/dreamshaper-xl-lightning"
    assert model["source"]["revision"] == "561086c22aba3925b1e8803a73857f061635c7c3"
    assert model["source"]["expected_sha256"] == "fdbe56354b8f876b736f24d3ad867ecd4140c019f57642ec8ddd878088d44f64"
    assert model["windows"]["sha256"] == "2b8407a7667fa1b8c6d5bad971309341bf370adbd5ce58e5e5812c677863c728"
    assert model["generation_defaults"] == {
        "width": 768,
        "height": 768,
        "steps": 8,
        "cfg": 2.0,
        "sampling_method": "dpm++2m_sde",
        "scheduler": "karras",
    }


def test_illustrious_v2_has_verified_identity_and_illustration_quality_profile():
    data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    model = next(item for item in data["models"] if item["model_id"] == "illustrious-xl-v2.0")
    assert model["display_name"] == "Illustrious XL v2.0（插画）"
    assert model["architecture"] == "SDXL"
    assert model["status"] == "installed"
    assert model["dmd2"]["enabled"] is False
    assert model["dmd2"]["variant"] == "standard"
    assert "android_reference" not in model
    assert model["source"]["repo_id"] == "OnomaAIResearch/Illustrious-XL-v2.0"
    assert model["source"]["revision"] == "69459c1fe6f46db41ab31e6114f05acc0e06bcaa"
    assert model["source"]["expected_sha256"] == "c2a1a3eaa13d4c107dc7e00c3fe830cab427aa026362740ea094745b3422a331"
    assert model["windows"]["path"] == r"E:\Dream\models\windows\gguf\illustrious-xl-v2.0-q8_0.gguf"
    assert model["windows"]["sha256"] == "0529ac9f17bc5470e5d5516c53a207df2e03706ae8614604141b405c92d1b0bb"
    # The October 10 pure-model audit superseded the original 768/CFG5 preset.
    # See docs/dream-windows/ILLUSTRIOUS_QUALITY_20261010.md; explicit old
    # requests remain covered separately by test_illustrious_defaults.py.
    assert model["generation_defaults"] == {
        "width": 1024,
        "height": 1024,
        "steps": 30,
        "cfg": 7.0,
        "sampling_method": "euler_a",
        "scheduler": "discrete",
    }


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


def test_validator_accepts_windows_only_model_without_android_reference():
    temp_parent = Path(r"E:\Dream\temp")
    temp_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="registry-test-", dir=temp_parent) as temp_dir:
        root = Path(temp_dir)
        source = root / "models" / "source" / "windows-only.safetensors"
        gguf = root / "models" / "windows" / "windows-only-q8_0.gguf"
        source.parent.mkdir(parents=True)
        gguf.parent.mkdir(parents=True)
        source.write_bytes(b"source")
        gguf.write_bytes(b"GGUF")
        registry = root / "model-registry.json"
        registry.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "dream_root": str(root),
                    "first_model_id": "windows-only",
                    "models": [
                        {
                            "model_id": "windows-only",
                            "display_name": "Windows Only",
                            "architecture": "SDXL",
                            "status": "installed",
                            "dmd2": {"enabled": False},
                            "source": {"path": str(source), "sha256": "a" * 64},
                            "windows": {
                                "format": "gguf",
                                "path": str(gguf),
                                "sha256": "b" * 64,
                            },
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(VALIDATOR),
                "-Root",
                str(root),
                "-RegistryPath",
                str(registry),
            ],
            cwd=ROOT,
            text=True,
            encoding="utf-8",
            capture_output=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "MODEL_REGISTRY_PASS" in result.stdout
