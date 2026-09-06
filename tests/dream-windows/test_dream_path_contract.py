from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP = ROOT / "scripts" / "bootstrap_e_drive.ps1"
ENV_SCRIPT = ROOT / "scripts" / "set_dream_env.ps1"


REQUIRED_RELATIVE_PATHS = {
    "app",
    "app/current",
    "app/versions",
    "app/runtime",
    "src",
    "models",
    "models/source",
    "models/windows",
    "models/windows/gguf",
    "models/windows/quantized",
    "models/windows/manifests",
    "models/research",
    "cache",
    "cache/huggingface",
    "cache/huggingface/hub",
    "cache/torch",
    "cache/diffusers",
    "cache/transformers",
    "cache/cuda",
    "cache/cmake",
    "cache/cargo",
    "cache/npm",
    "cache/build",
    "env",
    "env/python",
    "env/venv",
    "env/node",
    "env/rust",
    "env/tools",
    "data",
    "data/history",
    "data/favorites",
    "data/thumbnails",
    "data/metadata",
    "experiments",
    "experiments/fusion",
    "experiments/steps",
    "experiments/model_compare",
    "experiments/attention",
    "traces",
    "traces/runtime",
    "traces/latent",
    "traces/influence",
    "traces/attention",
    "exports",
    "logs",
    "temp",
    "builds",
    "builds/debug",
    "builds/release",
    "builds/installer",
    "backups",
    "ci",
    "ci/runner",
    "ci/work",
    "ci/cache",
}


def test_dream_bootstrap_scripts_exist():
    assert BOOTSTRAP.is_file(), BOOTSTRAP
    assert ENV_SCRIPT.is_file(), ENV_SCRIPT


def test_bootstrap_defaults_to_e_drive_and_declares_required_layout():
    text = BOOTSTRAP.read_text(encoding="utf-8")
    assert "E:\\Dream" in text
    assert "New-Item" in text
    for relative_path in REQUIRED_RELATIVE_PATHS:
        assert relative_path.replace("/", "\\") in text, relative_path


def test_environment_redirects_all_project_caches_to_e_drive():
    text = ENV_SCRIPT.read_text(encoding="utf-8")
    for variable in (
        "DREAM_HOME",
        "HF_HOME",
        "HUGGINGFACE_HUB_CACHE",
        "TORCH_HOME",
        "TRANSFORMERS_CACHE",
        "CARGO_HOME",
        "RUSTUP_HOME",
        "npm_config_cache",
        "TEMP",
        "TMP",
        "DREAM_MODEL_HOME",
        "DREAM_DATA_HOME",
        "DREAM_TRACE_HOME",
        "DREAM_EXPERIMENT_HOME",
    ):
        assert f"$env:{variable}" in text, variable
    assert "C:\\" not in text

