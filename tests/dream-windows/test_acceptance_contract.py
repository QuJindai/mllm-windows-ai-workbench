import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ORCHESTRATOR = ROOT / "tests" / "dream-windows" / "Invoke-DreamAcceptance.ps1"
GUIDE = ROOT / "docs" / "dream-windows" / "W0_W1_ACCEPTANCE.md"


def test_acceptance_orchestrator_and_guide_exist():
    assert ORCHESTRATOR.is_file()
    assert GUIDE.is_file()


def test_acceptance_report_contract_names_required_evidence():
    text = ORCHESTRATOR.read_text(encoding="utf-8")
    for marker in (
        "branch",
        "HEAD",
        "GPU",
        "VRAM",
        "CUDA",
        "model_identity",
        "model_path",
        "output_path",
        "seed",
        "steps",
        "cfg",
        "generation_time",
        "peak_vram",
        "peak_ram",
        "NO_C_DRIVE_DREAM_ASSET_PASS",
        "DREAM_ACCEPTANCE_PASS",
        "DREAM_ACCEPTANCE_BLOCKED",
        "acceptance.json",
    ):
        assert marker in text, marker


def test_acceptance_guide_requires_real_image_and_separates_blockers():
    text = GUIDE.read_text(encoding="utf-8")
    assert "does not generate a placeholder" in text
    assert "W1_PREFLIGHT_BLOCKED" in text
    assert "E:\\Dream" in text


def test_acceptance_orchestrator_includes_w2_gui_gates():
    text = ORCHESTRATOR.read_text(encoding="utf-8")
    for marker in (
        "gui_w2",
        "GUI_TESTS_PASS",
        "GUI_BUILD_PASS",
        "GUI_DPI_PASS",
        "GUI_E_DRIVE_PASS",
        "GUI_TAURI_BUILD_PASS",
        "W2_GUI_ACCEPTANCE.md",
    ):
        assert marker in text, marker
