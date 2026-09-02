#!/usr/bin/env python3
from pathlib import Path
import sys


def require(text: str, needle: str, label: str) -> None:
    if needle not in text:
        raise AssertionError(f"{label}: missing {needle!r}")


def forbid(text: str, needle: str, label: str) -> None:
    if needle in text:
        raise AssertionError(f"{label}: forbidden brittle evidence check {needle!r}")


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: test_h6r5_semantic_fidelity_contract.py <patched-root>", file=sys.stderr)
        return 2
    root = Path(sys.argv[1]).resolve()
    repo_root = Path(__file__).resolve().parents[2]
    workflow = (repo_root / ".github/workflows/s24u-image-harness-h6r5-build.yml").read_text(encoding="utf-8")
    gradle = (root / "app/build.gradle.kts").read_text(encoding="utf-8")
    pipeline = (root / "app/src/main/cpp/src/Pipeline.hpp").read_text(encoding="utf-8")
    main_cpp = (root / "app/src/main/cpp/src/main.cpp").read_text(encoding="utf-8")
    service = (root / "app/src/main/java/io/github/xororz/localdream/service/BackgroundGenerationService.kt").read_text(encoding="utf-8")
    screen = (root / "app/src/main/java/io/github/xororz/localdream/ui/screens/ModelRunScreen.kt").read_text(encoding="utf-8")
    html = (root / "app/src/main/assets/s24u_microscope/index.html").read_text(encoding="utf-8")
    js = (root / "app/src/main/assets/s24u_microscope/microscope.js").read_text(encoding="utf-8")

    require(gradle, "versionCode = 7411", "H6R5 versionCode")
    require(gradle, 'versionName = "2.8.1-s24u-h6r5"', "H6R5 versionName")

    for needle in (
        "model_id", "model_display_name", "model_backend_type", "model_is_dmd2",
        "model_loras", "scheduler_name", "generation_seed", "generation_steps",
        "generation_cfg", "unet_sha256",
    ):
        require(service + screen + js + main_cpp, needle, f"model identity field {needle}")
    require(js, "MODEL IDENTITY", "model identity UI")

    for mode in ("first_only", "equal_mean", "token_weighted", "anchor_residual"):
        require(screen + js, mode, f"fusion experiment mode {mode}")
    for needle in ("SEMANTIC A/B", "same seed", "8 / 16 / 24", "experiment_id", "result_sha256"):
        require(screen + js + service, needle, f"semantic experiment evidence {needle}")
    require(screen, "h6r5ExperimentRunning", "A/B session running guard")
    require(screen, "enabled = !isRunning && !h6r5ExperimentRunning", "A/B controls stay disabled between variants")
    require(screen, "import androidx.compose.material3.OutlinedButton", "A/B OutlinedButton import")

    # GNU strings scans DEX as ASCII by default. UTF-8 punctuation such as the
    # middle dot in the human-facing button labels splits one logical string
    # into separate output fragments. The APK gate therefore must use stable
    # ASCII evidence for DEX checks, while source/UI contracts retain the full
    # Unicode labels.
    forbid(workflow, "grep -F '4 Fusion · same seed' /tmp/current.strings", "Unicode DEX fusion grep")
    forbid(workflow, "grep -F '8 / 16 / 24 · same seed' /tmp/current.strings", "Unicode DEX steps grep")
    require(workflow, "grep -F '4 Fusion' /tmp/current.strings", "ASCII DEX fusion evidence")
    require(workflow, "grep -F '8 / 16 / 24' /tmp/current.strings", "ASCII DEX steps evidence")

    require(pipeline, "processPromptPairChunks", "direct token-preserving inference")
    require(js, "TOKEN PRESERVATION", "token preservation UI")

    require(service + js, "influence_image_status", "influence image coverage status")
    require(js + html, "INFLUENCE IMAGE COVERAGE", "influence coverage UI")

    require(js, "renderHumanReadableTokens", "human-readable token renderer")
    require(html, "RAW BPE", "raw BPE folded evidence label")

    print("H6R5_SEMANTIC_FIDELITY_CONTRACT_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
