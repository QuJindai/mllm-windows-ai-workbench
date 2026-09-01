#!/usr/bin/env python3
from pathlib import Path
import sys


def require(text: str, needle: str, label: str) -> None:
    if needle not in text:
        raise AssertionError(f"{label}: missing {needle!r}")


def forbid(text: str, needle: str, label: str) -> None:
    if needle in text:
        raise AssertionError(f"{label}: forbidden {needle!r}")


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: test_h6r3_process_dynamics_contract.py <h6r3-task3-root>", file=sys.stderr)
        return 2
    root = Path(sys.argv[1])
    pipeline = (root / "app/src/main/cpp/src/Pipeline.hpp").read_text(encoding="utf-8")
    main_cpp = (root / "app/src/main/cpp/src/main.cpp").read_text(encoding="utf-8")
    service = (root / "app/src/main/java/io/github/xororz/localdream/service/BackgroundGenerationService.kt").read_text(encoding="utf-8")
    screen = (root / "app/src/main/java/io/github/xororz/localdream/ui/screens/ModelRunScreen.kt").read_text(encoding="utf-8")
    html = (root / "app/src/main/assets/s24u_microscope/index.html").read_text(encoding="utf-8")
    js = (root / "app/src/main/assets/s24u_microscope/microscope.js").read_text(encoding="utf-8")

    for field in (
        "latent_delta", "delta_l2", "delta_mean_abs", "latent_cosine",
        "latent_mean", "latent_std", "dynamics_unet_ms", "dynamics_scheduler_ms",
    ):
        require(pipeline, field, f"native {field}")
        require(main_cpp, f'"{field}"', f"serialized {field}")
    require(pipeline, "computeLatentDynamicsMetrics", "dynamics metric function")
    require(pipeline, "renderLatentDeltaPreview", "delta spatial renderer")
    require(pipeline, "xt::xarray<float> latents_before_step = xt::eval(latents);", "pre-step latent snapshot")
    require(pipeline, 'dynamics_trace.phase = "latent_delta"', "dynamics trace phase")

    require(service, "data class DynamicsSample", "Android dynamics model")
    require(service, "dynamicsSamples: List<DynamicsSample>", "bounded dynamics history")
    require(service, 'event.phase == "latent_delta"', "dynamics reducer")
    require(service, "takeLast(8)", "bounded 8-step dynamics")
    require(screen, "fun dynamicsJson", "dynamics JSON bridge")
    require(screen, '"dynamics_samples"', "dynamics bootstrap")
    require(screen, '"dynamics_samples_delta"', "drop-free dynamics delta media")

    require(html, "PROCESS DYNAMICS", "process dynamics heading")
    require(html, "Δzₜ", "delta latent explanation")
    require(html, 'id="dynamics-metrics"', "dynamics metric UI")
    require(html, 'id="dynamics-series"', "dynamics convergence series")
    require(html, "DECODED PREVIEW", "secondary decoded preview")
    require(js, "renderProcessDynamics", "process dynamics renderer")
    require(js, "dynamics_samples", "dynamics history")
    require(js, "delta_l2", "dynamics delta L2 UI")
    require(js, "latent_cosine", "dynamics cosine UI")
    require(js, "dynamics_samples_delta", "dynamics incremental media")
    forbid(js, "const processFrames=usingLatentFallback?latents:previews", "forbid duplicate latent fallback")
    forbid(js, "showFrame('process',previews.length?previews:latents", "forbid process latent contact-sheet fallback")

    print("H6R3_PROCESS_DYNAMICS_CONTRACT_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
