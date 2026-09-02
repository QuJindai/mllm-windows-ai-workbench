#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


def require(text: str, needle: str, label: str) -> None:
    if needle not in text:
        raise AssertionError(f"{label}: missing {needle!r}")


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: test_h6r3_fusion_lab_contract.py <h6r3-task2-local-dream-root>", file=sys.stderr)
        return 2

    root = Path(sys.argv[1]).resolve()
    pipeline = (root / "app/src/main/cpp/src/Pipeline.hpp").read_text(encoding="utf-8")
    main_cpp = (root / "app/src/main/cpp/src/main.cpp").read_text(encoding="utf-8")
    service = (root / "app/src/main/java/io/github/xororz/localdream/service/BackgroundGenerationService.kt").read_text(encoding="utf-8")
    screen = (root / "app/src/main/java/io/github/xororz/localdream/ui/screens/ModelRunScreen.kt").read_text(encoding="utf-8")
    js = (root / "app/src/main/assets/s24u_microscope/microscope.js").read_text(encoding="utf-8")

    require(pipeline, 'std::string fusion_mode = "equal_mean";', "equal-mean production default")
    require(pipeline, "float fusion_alpha = 0.5f;", "anchor residual alpha default")
    require(pipeline, 'req.fusion_mode == "equal_mean"', "explicit equal-mean branch")
    require(pipeline, "noise_pred = xt::eval(noise_pred / (float)conds.size())", "unchanged equal-mean formula")

    for mode in ("first_only", "equal_mean", "token_weighted", "anchor_residual"):
        require(pipeline, f'"{mode}"', f"native fusion mode {mode}")
        require(screen, f'"{mode}"', f"phone fusion selector {mode}")
    require(pipeline, 'req.fusion_mode == "first_only" ? 1', "first-only active chunk count")
    # H6R3 used reconstructed-text token counts. H6R4 replaces them with exact
    # content counts attached to the already-encoded Conditioning chunks.
    if "positive_content_tokens" in pipeline:
        require(pipeline, "negative_content_tokens", "direct negative chunk token weights")
    else:
        require(pipeline, "promptContentTokenCount", "legacy real chunk token weights")
    require(pipeline, "fusion_token_weights", "token weight vector")
    require(pipeline, "fusion_effective_weights", "effective fusion weight vector")
    require(pipeline, "anchor + req.fusion_alpha * residual", "anchor residual fusion")

    require(pipeline, "const bool request_skip_uncond", "request skip-uncond fact")
    require(pipeline, "request_skip_uncond\n                                         ? pos_tokens", "cfg1 positive-only fusion weighting")
    require(pipeline, ": std::max(pos_tokens, neg_tokens)", "guided paired-chunk weighting")

    require(screen, "var fusionMode by remember", "fusion selector state")
    require(screen, 'putExtra("fusion_mode", fusionMode)', "fusion mode intent extra")
    require(screen, 'putExtra("fusion_alpha", fusionAlpha)', "fusion alpha intent extra")
    require(service, 'intent.getStringExtra("fusion_mode") ?: "equal_mean"', "service fusion mode")
    require(service, 'put("fusion_mode", fusionMode)', "HTTP fusion mode")
    require(main_cpp, 'json.value("fusion_mode", std::string("equal_mean"))', "native request fusion mode")

    require(pipeline, "fusion_mode", "trace fusion mode")
    require(pipeline, "fusion_weights", "trace fusion weights")
    require(main_cpp, '"fusion_weights"', "fusion weights serialization")
    require(service, "fusionWeights", "Android fusion weights")
    require(js, "fusion_mode", "WebView fusion mode")
    require(js, "fusion_weights", "WebView fusion weights")
    require(js, "FUSION LAB", "fusion lab runtime label")

    print("H6R3_FUSION_LAB_CONTRACT_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
