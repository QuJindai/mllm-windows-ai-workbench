#!/usr/bin/env python3
from pathlib import Path
import sys


def require(text: str, needle: str, label: str) -> None:
    if needle not in text:
        raise AssertionError(f"{label}: missing {needle!r}")


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: test_h4_visual_microscope_contract.py <h4-local-dream-root>", file=sys.stderr)
        return 2
    root = Path(sys.argv[1])

    gradle = (root / "app/build.gradle.kts").read_text(encoding="utf-8")
    text_encoder = (root / "app/src/main/cpp/src/TextEncoder.hpp").read_text(encoding="utf-8")
    main_cpp = (root / "app/src/main/cpp/src/main.cpp").read_text(encoding="utf-8")
    service = (root / "app/src/main/java/io/github/xororz/localdream/service/BackgroundGenerationService.kt").read_text(encoding="utf-8")
    screen = (root / "app/src/main/java/io/github/xororz/localdream/ui/screens/ModelRunScreen.kt").read_text(encoding="utf-8")

    require(gradle, "versionCode = 7404", "H4 versionCode")
    require(gradle, 'versionName = "2.8.1-s24u-h4"', "H4 versionName")
    require(gradle, 'applicationId = "io.github.xororz.localdream.s24uharness"', "stable package")

    # Real long-prompt expansion without changing the 77-slot QNN graph.
    require(text_encoder, "kS24uClipChunkLen = 77", "fixed CLIP graph")
    require(text_encoder, "kS24uClipContentTokens = 75", "fixed content budget per graph")
    require(text_encoder, "kS24uClipChunks = 8", "H4 eight chunks")
    require(main_cpp, '"positive_input_tokens"', "positive input token truth")
    require(main_cpp, '"positive_effective_tokens"', "positive effective token truth")
    require(main_cpp, '"positive_truncated_tokens"', "positive truncation truth")
    require(main_cpp, '"negative_input_tokens"', "negative input token truth")
    require(main_cpp, '"negative_effective_tokens"', "negative effective token truth")
    require(main_cpp, '"negative_truncated_tokens"', "negative truncation truth")
    require(main_cpp, '"positive_chunk_tokens"', "positive per-chunk tokens")
    require(main_cpp, '"negative_chunk_tokens"', "negative per-chunk tokens")
    require(main_cpp, '"max_chunks"', "configured maximum chunks")

    # Reducer correctness: zero-duration scheduler is observed; skip-uncond is phase-owned;
    # trace progress is monotonic and completion is 100%.
    require(service, "val schedulerSeen: Boolean = false", "scheduler observed flag")
    require(service, "val unetSeen: Boolean = false", "UNet observed flag")
    require(service, "val traceProgress: Float = 0f", "trace progress")
    require(service, "positiveInputTokens", "positive input count state")
    require(service, "positiveEffectiveTokens", "positive effective count state")
    require(service, "positiveTruncatedTokens", "positive truncation count state")
    require(service, "negativeInputTokens", "negative input count state")
    require(service, "negativeEffectiveTokens", "negative effective count state")
    require(service, "negativeTruncatedTokens", "negative truncation count state")
    require(service, 'if (event.phase == "unet_step") event.skipUncond else previous.skipUncond', "phase-owned skip-uncond")
    require(service, '"scheduler_step" -> next.copy(', "scheduler reducer")
    require(service, "schedulerSeen = true", "scheduler seen true")
    require(service, '"complete" -> next.copy(totalMs = event.durationMs, traceProgress = 1f)', "complete is 100 percent")

    # Compose hosts a local-only WebView and streams the live snapshot as JSON.
    require(screen, "S24U_H4_VISUAL_MICROSCOPE", "H4 Compose marker")
    require(screen, 'file:///android_asset/s24u_microscope/index.html', "offline visualizer URL")
    require(screen, "AndroidView", "WebView Compose host")
    require(screen, "WebView", "WebView host")
    require(screen, "evaluateJavascript", "live JSON push")
    require(screen, "shouldInterceptRequest", "remote request blocking")
    require(screen, "allowUniversalAccessFromFileURLs = false", "WebView universal access blocked")
    require(screen, "allowFileAccessFromFileURLs = false", "WebView file cross-access blocked")
    require(screen, "positive_input_tokens", "serialized positive budget")
    require(screen, "trace_progress", "serialized trace progress")

    asset_root = root / "app/src/main/assets/s24u_microscope"
    index = (asset_root / "index.html").read_text(encoding="utf-8")
    css = (asset_root / "microscope.css").read_text(encoding="utf-8")
    js = (asset_root / "microscope.js").read_text(encoding="utf-8")

    require(index, "S24U H4 Visual Microscope", "visualizer marker")
    require(index, "pipeline-svg", "SVG pipeline host")
    require(index, "公式联动", "formula panel")
    require(index, "真实时间轴", "timeline panel")
    require(index, "Cross-attention：未采集", "truthful attention state")
    require(index, "专家证据", "collapsed expert evidence")
    require(css, ".pipeline-node", "pipeline node styling")
    require(css, ".timeline-bar", "timeline styling")
    require(css, ".token-slot", "token matrix styling")
    require(js, "window.S24UMicroscope", "visualizer API")
    require(js, "renderPipeline", "pipeline rendering")
    require(js, "renderTokenChunks", "token chunk rendering")
    require(js, "renderFormulas", "formula rendering")
    require(js, "renderTimeline", "timeline rendering")
    require(js, "positive_truncated_tokens", "truncation visualization")
    require(js, "scheduler_seen", "zero-duration scheduler observation")

    print("H4_VISUAL_MICROSCOPE_CONTRACT_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
