#!/usr/bin/env python3
from pathlib import Path
import sys


def require(text: str, needle: str, label: str) -> None:
    if needle not in text:
        raise AssertionError(f"{label}: missing {needle!r}")


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: test_h3_microscope_contract.py <local-dream-root>", file=sys.stderr)
        return 2
    root = Path(sys.argv[1])

    gradle = (root / "app/build.gradle.kts").read_text(encoding="utf-8")
    main_cpp = (root / "app/src/main/cpp/src/main.cpp").read_text(encoding="utf-8")
    pipeline = (root / "app/src/main/cpp/src/Pipeline.hpp").read_text(encoding="utf-8")
    service = (
        root
        / "app/src/main/java/io/github/xororz/localdream/service/BackgroundGenerationService.kt"
    ).read_text(encoding="utf-8")
    screen = (
        root
        / "app/src/main/java/io/github/xororz/localdream/ui/screens/ModelRunScreen.kt"
    ).read_text(encoding="utf-8")

    require(gradle, "versionCode = 7403", "H3 versionCode")
    require(gradle, 'versionName = "2.8.1-s24u-h3"', "H3 versionName")

    # Native trace protocol must be real SSE emitted by the generation backend.
    require(pipeline, "struct MicroscopeTraceEvent", "native trace event type")
    require(pipeline, "using MicroscopeTraceCallback", "native trace callback")
    require(pipeline, 'phase = "clip"', "CLIP trace")
    require(pipeline, 'phase = "unet_step"', "UNet trace")
    require(pipeline, 'phase = "scheduler_step"', "scheduler trace")
    require(pipeline, 'phase = "vae_decode"', "VAE trace")
    require(pipeline, 'phase = "complete"', "complete trace")
    require(pipeline, "chunk_count", "long-prompt chunk count in trace")
    require(pipeline, "timestep", "diffusion timestep in trace")
    require(pipeline, "duration_ms", "real stage duration in trace")

    require(main_cpp, '{"type", "trace"}', "SSE trace event serialization")
    require(main_cpp, 'event: trace\\ndata:', "SSE trace wire event")
    require(main_cpp, 'phase = "prompt"', "prompt/token trace")
    require(main_cpp, 'positive_token_ids', "positive token ids")
    require(main_cpp, 'negative_token_ids', "negative token ids")
    require(main_cpp, 'positive_chunks', "positive prompt chunks")
    require(main_cpp, 'negative_chunks', "negative prompt chunks")

    # Android service must retain a bounded, observable stream instead of only a %.
    require(service, "data class MicroscopeEvent", "Android microscope event")
    require(service, "data class MicroscopeSnapshot", "Android microscope snapshot")
    require(service, "microscopeState: StateFlow<MicroscopeSnapshot>", "microscope StateFlow")
    require(service, '"trace" ->', "trace SSE parser")
    require(service, "takeLast(127)", "bounded trace event history")
    require(service, "latestUnetMs", "UNet timing state")
    require(service, "clipMs", "CLIP timing state")
    require(service, "vaeMs", "VAE timing state")

    # UI contract: a real fourth page with prompt/token, live pipeline and bottom output.
    require(screen, "pageCount = { 4 }", "four-page pager")
    require(screen, '"显微镜"', "microscope tab label")
    require(screen, "fun MicroscopePage()", "microscope page")
    require(screen, "BackgroundGenerationService.microscopeState.collectAsState()", "live microscope subscription")
    require(screen, '"Prompt / Token"', "prompt token panel")
    require(screen, '"实时计算链"', "live compute chain panel")
    require(screen, '"UNet / Scheduler"', "UNet scheduler panel")
    require(screen, '"底部实时输出"', "bottom live output panel")
    require(screen, "microscope.events.takeLast", "bottom event stream")
    require(screen, "pagerState.animateScrollToPage(3)", "jump to microscope action")

    print("H3_MICROSCOPE_CONTRACT_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
