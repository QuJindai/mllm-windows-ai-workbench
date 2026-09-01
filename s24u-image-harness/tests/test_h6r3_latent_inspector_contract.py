#!/usr/bin/env python3
from pathlib import Path
import sys


def require(text: str, needle: str, label: str) -> None:
    if needle not in text:
        raise AssertionError(f"{label}: missing {needle!r}")


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: test_h6r3_latent_inspector_contract.py <h6r3-task4-root>", file=sys.stderr)
        return 2
    root = Path(sys.argv[1])
    pipeline = (root / "app/src/main/cpp/src/Pipeline.hpp").read_text(encoding="utf-8")
    main_cpp = (root / "app/src/main/cpp/src/main.cpp").read_text(encoding="utf-8")
    service = (root / "app/src/main/java/io/github/xororz/localdream/service/BackgroundGenerationService.kt").read_text(encoding="utf-8")
    screen = (root / "app/src/main/java/io/github/xororz/localdream/ui/screens/ModelRunScreen.kt").read_text(encoding="utf-8")
    html = (root / "app/src/main/assets/s24u_microscope/index.html").read_text(encoding="utf-8")
    js = (root / "app/src/main/assets/s24u_microscope/microscope.js").read_text(encoding="utf-8")

    for field in ("channel_stats", "channel_correlation", "channel_histograms"):
        require(pipeline, field, f"native {field}")
        require(main_cpp, f'"{field}"', f"serialized {field}")
    require(pipeline, "computeLatentChannelInspector", "latent inspector metrics")
    require(pipeline, "kLatentHistogramBins = 32", "32-bin histograms")

    require(service, "channelStats: List<Float>", "Android channel stats")
    require(service, "channelCorrelation: List<Float>", "Android correlations")
    require(service, "channelHistograms: List<Float>", "Android histograms")
    require(screen, 'put("channel_stats"', "latent stats WebView bridge")
    require(screen, 'put("channel_correlation"', "latent correlation bridge")
    require(screen, 'put("channel_histograms"', "latent histogram bridge")

    require(html, "LATENT STATE INSPECTOR", "latent inspector heading")
    require(html, 'id="latent-channel-grid"', "four channel grid")
    require(html, 'id="latent-channel-stats"', "channel stats UI")
    require(html, 'id="latent-correlation"', "correlation matrix UI")
    require(html, 'id="latent-histogram"', "histogram UI")
    require(html, 'id="latent-compare"', "step comparison UI")
    require(js, "renderLatentInspector", "latent inspector renderer")
    require(js, "backgroundSize='200% 200%'", "contact-sheet quadrant crop")
    require(js, "channel_stats", "latent stats JS")
    require(js, "channel_correlation", "latent correlation JS")
    require(js, "channel_histograms", "latent histogram JS")
    require(js, "previous / current / final", "latent step comparison semantics")

    print("H6R3_LATENT_INSPECTOR_CONTRACT_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
