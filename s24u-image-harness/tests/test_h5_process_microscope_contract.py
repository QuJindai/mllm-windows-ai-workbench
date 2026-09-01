#!/usr/bin/env python3
from pathlib import Path
import sys


def require(text: str, needle: str, label: str) -> None:
    if needle not in text:
        raise AssertionError(f"{label}: missing {needle!r}")


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: test_h5_process_microscope_contract.py <local-dream-root>", file=sys.stderr)
        return 2
    root = Path(sys.argv[1])

    gradle = (root / "app/build.gradle.kts").read_text(encoding="utf-8")
    pipeline = (root / "app/src/main/cpp/src/Pipeline.hpp").read_text(encoding="utf-8")
    main_cpp = (root / "app/src/main/cpp/src/main.cpp").read_text(encoding="utf-8")
    service = (root / "app/src/main/java/io/github/xororz/localdream/service/BackgroundGenerationService.kt").read_text(encoding="utf-8")
    screen = (root / "app/src/main/java/io/github/xororz/localdream/ui/screens/ModelRunScreen.kt").read_text(encoding="utf-8")
    html = (root / "app/src/main/assets/s24u_microscope/index.html").read_text(encoding="utf-8")
    css = (root / "app/src/main/assets/s24u_microscope/microscope.css").read_text(encoding="utf-8")
    js = (root / "app/src/main/assets/s24u_microscope/microscope.js").read_text(encoding="utf-8")

    require(gradle, "versionCode = 7405", "H5 versionCode")
    require(gradle, 'versionName = "2.8.1-s24u-h5"', "H5 versionName")

    # Real process imagery: Local Dream's native VAE preview path must be forced
    # on for the microscope harness (except unsupported ultrafix) and retained.
    require(service, "data class MicroscopePreview", "process preview model")
    require(service, "processPreviews: List<MicroscopePreview>", "preview history")
    require(service, "microscopePreviewStride", "bounded preview stride")
    require(service, 'put("show_diffusion_process", if (ultrafix) false else true)', "real VAE previews enabled")
    require(service, 'message.optInt("preview_index", 0)', "preview index parser")
    require(service, "processPreviews.takeLast", "bounded preview history")

    # Cheap internal-state imagery: every diffusion step emits a real 4-channel
    # latent visualization without pretending it is an UNet feature map.
    require(pipeline, "#include <limits>", "numeric limits include")
    require(pipeline, "renderLatentChannelsPreview", "latent channel renderer")
    require(pipeline, "std::numeric_limits<float>", "latent normalization limits")
    require(pipeline, 'phase = "latent_map"', "latent map trace phase")
    require(pipeline, "image_base64", "trace image payload")
    require(main_cpp, '"image_base64"', "latent image SSE serialization")
    require(service, "latentMaps: List<MicroscopePreview>", "latent map history")

    # H5 UI must look like the Local Dream host instead of a separate dark demo.
    require(screen, "S24U_H5_PROCESS_MICROSCOPE", "H5 runtime marker")
    require(html, 'data-panel="overview"', "overview panel")
    require(html, 'data-panel="process"', "process panel")
    require(html, 'data-panel="mechanism"', "mechanism panel")
    require(html, 'data-panel="expert"', "expert panel")
    require(html, 'id="process-main-image"', "process main image")
    require(html, 'id="process-scrubber"', "step scrubber")
    require(html, 'id="latent-main-image"', "latent map viewer")
    require(css, "--primary: #4285f4", "Local Dream blue")
    require(css, "--page: #f7f7fa", "Local Dream light page")
    require(css, "content-visibility:auto", "offscreen render containment")

    # Smoothness: coalesce rapid native trace updates and only render changed
    # sections / active panel instead of rebuilding the whole document per SSE.
    require(js, "requestAnimationFrame", "RAF coalescing")
    require(js, "pendingSnapshot", "coalesced snapshot state")
    require(js, "Object.assign({},pendingSnapshot||{},snapshot||{})", "partial snapshot merge")
    require(js, "activePanel", "panel virtualization")
    require(js, "renderProcess", "process image renderer")
    require(js, "process_previews", "process preview bridge")
    require(js, "latent_maps", "latent map bridge")
    require(js, "lastEventCount", "timeline diff gate")
    require(screen, "mediaRevision", "media telemetry bridge split")
    require(screen, "microscope.events.takeLast(48)", "bounded Android event bridge")

    # Attribution remains evidence-based: no fake attention heatmap.
    require(html, "Cross-attention 未采集", "honest attention state")

    print("H5_PROCESS_MICROSCOPE_CONTRACT_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
