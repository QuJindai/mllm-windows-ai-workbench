#!/usr/bin/env python3
from pathlib import Path
import sys


def require(text: str, needle: str, label: str) -> None:
    if needle not in text:
        raise AssertionError(f"{label}: missing {needle!r}")


def require_any(text: str, needles: tuple[str, ...], label: str) -> None:
    if not any(needle in text for needle in needles):
        # Keep the original H6 failure text stable because the H6 RED workflow
        # intentionally greps it before the H6 patch is applied.
        raise AssertionError(f"{label}: missing {needles[0]!r}")


def forbid(text: str, needle: str, label: str) -> None:
    if needle in text:
        raise AssertionError(f"{label}: forbidden {needle!r}")


def require_order(text: str, first: str, second: str, label: str) -> None:
    first_index = text.find(first)
    second_index = text.find(second)
    if first_index < 0 or second_index < 0 or first_index >= second_index:
        raise AssertionError(f"{label}: expected {first!r} before {second!r}")


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: test_h6_conditioning_influence_contract.py <local-dream-root>", file=sys.stderr)
        return 2
    root = Path(sys.argv[1])

    gradle = (root / "app/build.gradle.kts").read_text(encoding="utf-8")
    pipeline = (root / "app/src/main/cpp/src/Pipeline.hpp").read_text(encoding="utf-8")
    main_cpp = (root / "app/src/main/cpp/src/main.cpp").read_text(encoding="utf-8")
    service = (root / "app/src/main/java/io/github/xororz/localdream/service/BackgroundGenerationService.kt").read_text(encoding="utf-8")
    screen = (root / "app/src/main/java/io/github/xororz/localdream/ui/screens/ModelRunScreen.kt").read_text(encoding="utf-8")
    html = (root / "app/src/main/assets/s24u_microscope/index.html").read_text(encoding="utf-8")
    js = (root / "app/src/main/assets/s24u_microscope/microscope.js").read_text(encoding="utf-8")

    # Later H6 revisions may extend semantics and microscope UI while carrying
    # the same H6 influence observation path forward. Version bumps are allowed;
    # every behavioral assertion below remains mandatory.
    require_any(
        gradle,
        ("versionCode = 7406", "versionCode = 7407", "versionCode = 7408", "versionCode = 7409"),
        "H6 versionCode",
    )
    require_any(
        gradle,
        (
            'versionName = "2.8.1-s24u-h6"',
            'versionName = "2.8.1-s24u-h6r1"',
            'versionName = "2.8.1-s24u-h6r2"',
            'versionName = "2.8.1-s24u-h6r3"',
        ),
        "H6 versionName",
    )

    # H2 equal-mean fusion remains the default until H6R3 phone evidence
    # explicitly approves another mode. The diagnostic lab may add alternatives,
    # but this production default must still exist.
    require(pipeline, "noise_pred = xt::eval(noise_pred / (float)conds.size())", "unchanged H2 default fusion")
    require(pipeline, "std::vector<xt::xarray<float>> chunk_predictions", "current-step chunk prediction retention")
    require(pipeline, "chunk_predictions.reserve(conds.size())", "bounded chunk prediction reserve")
    require(pipeline, "chunk_predictions.push_back(chunk_pred)", "per-chunk prediction capture")

    # Real conditioning influence telemetry. These metrics are calculated from
    # chunk_pred and the exact fused noise_pred used by the scheduler.
    require(pipeline, "conditioning_influence", "influence trace phase")
    require(pipeline, "influence_chunk_index", "influence chunk index")
    require(pipeline, "influence_chunk_count", "influence chunk count")
    require(pipeline, "influence_mean_abs", "influence mean abs")
    require(pipeline, "influence_l2", "influence L2")
    require(pipeline, "influence_fused_cosine", "influence cosine")
    require(pipeline, "influence_delta_l2", "influence delta L2")
    require(pipeline, "renderConditioningInfluencePreview", "real spatial influence renderer")
    require(pipeline, "xt::abs(chunk_pred - fused_pred)", "real chunk/fused difference")
    require(main_cpp, '"influence_chunk_index"', "native SSE influence serialization")
    require(main_cpp, '"influence_delta_l2"', "native SSE influence metric serialization")

    # Temporary raw predictions must be released before scheduler work.
    require(pipeline, "chunk_predictions.clear();", "release per-step chunk tensors")
    require_order(
        pipeline,
        "chunk_predictions.clear();",
        "auto scheduler_start = std::chrono::high_resolution_clock::now();",
        "chunk tensor release before scheduler",
    )

    # Android stores compact metrics/images only; no raw prediction tensors
    # cross the native boundary.
    require(service, "data class InfluenceSample", "Android influence model")
    require(service, "influenceSamples: List<InfluenceSample>", "bounded influence history")
    require(service, 'event.phase == "conditioning_influence"', "influence reducer")
    require(service, "takeLast(32)", "bounded influence history cap")
    require(screen, "S24U_H6_CONDITIONING_INFLUENCE", "compiled H6 marker")
    require(screen, 'put("influence_samples"', "influence bootstrap JSON")

    # StateFlow is intentionally conflated. The bridge must batch every retained
    # influence sample newer than the last WebView revision.
    require(screen, "previousInfluenceRevision", "drop-free influence revision")
    require(screen, "influenceSamples.filter", "drop-free influence delta selection")
    require(screen, "it.diffusionStep * 100 + it.chunkIndex + 1 > previousInfluenceRevision", "monotonic influence delta filter")
    require(screen, 'put("influence_samples_delta"', "batched influence delta JSON")
    require(screen, "mediaRolledBack", "generation restart revision rollback")
    forbid(screen, 'put("influence_sample", influenceJson(it))', "forbid last-only influence bridge")
    require(js, "media.influence_samples_delta", "batched influence delta receiver")
    require(js, "influence_samples_delta.forEach", "batched influence delta replay")

    # Conditioning difference is never labeled as token-level attention.
    require(html, 'data-panel="influence"', "Influence panel")
    require(html, 'data-tab="influence"', "Influence tab")
    require(html, 'id="influence-main-image"', "Influence image")
    require(html, 'id="influence-step-scrubber"', "Influence step scrubber")
    require(html, 'id="influence-chunks"', "Influence chunk selector")
    require(html, "不是 cross-attention", "truthful influence wording")
    require_any(
        html,
        ("Cross-attention 未采集", "当前不可观测：Cross-attention 未导出", "Production QNN 图未导出"),
        "preserved honest attribution state",
    )
    require(js, "influence_samples", "Influence local history")
    require(js, "renderInfluence", "Influence renderer")
    require(js, "activePanel==='influence'", "Influence active-panel virtualization")

    print("H6_CONDITIONING_INFLUENCE_CONTRACT_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
