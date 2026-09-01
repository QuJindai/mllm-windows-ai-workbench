#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


def require(text: str, needle: str, label: str) -> None:
    if needle not in text:
        raise AssertionError(f"{label}: missing {needle!r}")


def forbid(text: str, needle: str, label: str) -> None:
    if needle in text:
        raise AssertionError(f"{label}: forbidden {needle!r}")


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: test_h6r3_semantic_fidelity_contract.py <patched-local-dream-root>", file=sys.stderr)
        return 2

    root = Path(sys.argv[1]).resolve()
    gradle = (root / "app/build.gradle.kts").read_text(encoding="utf-8")
    pipeline = (root / "app/src/main/cpp/src/Pipeline.hpp").read_text(encoding="utf-8")
    main_cpp = (root / "app/src/main/cpp/src/main.cpp").read_text(encoding="utf-8")
    service = (root / "app/src/main/java/io/github/xororz/localdream/service/BackgroundGenerationService.kt").read_text(encoding="utf-8")
    screen = (root / "app/src/main/java/io/github/xororz/localdream/ui/screens/ModelRunScreen.kt").read_text(encoding="utf-8")
    html = (root / "app/src/main/assets/s24u_microscope/index.html").read_text(encoding="utf-8")
    js = (root / "app/src/main/assets/s24u_microscope/microscope.js").read_text(encoding="utf-8")

    require(gradle, "versionCode = 7409", "H6R3 versionCode")
    require(gradle, 'versionName = "2.8.1-s24u-h6r3"', "H6R3 versionName")
    require(screen, 'put("h6r3_marker", "S24U_H6R3_SEMANTIC_FIDELITY")', "H6R3 DEX marker")

    # CFG / negative-prompt truthfulness. Encoding and effective guidance are
    # separate facts: cfg=1 on QNN may encode negative text but give it zero
    # effective weight because unconditional execution is skipped.
    require(pipeline, "negative_effective_weight", "native negative effective weight")
    require(pipeline, "positive_effective_weight", "native positive effective weight")
    require(pipeline, "negative_encoded", "native negative encoded state")
    require(main_cpp, '"negative_effective_weight"', "guidance telemetry serialization")
    require(service, "negativeEffectiveWeight", "Android guidance state")
    require(js, "negative_effective_weight", "WebView guidance payload")
    require(js, "NEG effective", "truthful CFG UI")

    # Process Dynamics must be based on adjacent latent change, not the H6R2
    # fallback that reused latent_maps as the process page's primary visual.
    require(pipeline, "latent_delta", "latent delta telemetry")
    require(pipeline, "delta_l2", "latent delta L2")
    require(pipeline, "delta_mean_abs", "latent delta mean abs")
    require(pipeline, "latent_cosine", "adjacent latent cosine")
    require(js, "renderProcessDynamics", "Process Dynamics renderer")
    forbid(js, "const processFrames=usingLatentFallback?latents:previews", "forbid duplicate latent fallback process renderer")

    # Latent State Inspector must expose the four channels as separate state
    # summaries rather than only the existing 2x2 contact sheet.
    require(pipeline, "channel_stats", "channel statistics telemetry")
    require(pipeline, "channel_correlation", "channel correlation telemetry")
    require(js, "renderLatentInspector", "latent inspector renderer")
    require(html, "LATENT STATE INSPECTOR", "latent inspector heading")

    # Runtime compute graph replaces the low-density architecture strip.
    require(html, "RUNTIME COMPUTE GRAPH", "runtime compute graph heading")
    require(js, "renderRuntimeGraph", "runtime graph renderer")
    for field in ("backend", "shape", "call_count", "duration_ms", "execution_state"):
        require(js, field, f"runtime graph {field}")
    require(js, "MNN / CPU", "CLIP backend truth")
    require(js, "QNN / HTP", "UNet/VAE backend truth")
    require(js, "Scheduler / CPU", "Scheduler backend truth")

    # Cross-attention remains explicitly unavailable in Production graph and
    # points to the H7 Debug UNet path rather than pretending H6 influence is it.
    require(html, "Production QNN 图未导出", "production attention capability boundary")
    require(html, "Debug UNet Graph", "H7 attention path")

    print("H6R3_SEMANTIC_FIDELITY_CONTRACT_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
