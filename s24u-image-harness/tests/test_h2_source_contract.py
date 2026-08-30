#!/usr/bin/env python3
from pathlib import Path
import sys


def require(cond: bool, message: str) -> None:
    if not cond:
        raise AssertionError(message)


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: test_h2_source_contract.py <patched-local-dream-root>", file=sys.stderr)
        return 2

    root = Path(sys.argv[1])
    gradle = (root / "app/build.gradle.kts").read_text(encoding="utf-8")
    screen = (root / "app/src/main/java/io/github/xororz/localdream/ui/screens/ModelRunScreen.kt").read_text(encoding="utf-8")
    strings = (root / "app/src/main/res/values/strings.xml").read_text(encoding="utf-8")
    text_encoder = (root / "app/src/main/cpp/src/TextEncoder.hpp").read_text(encoding="utf-8")
    pipeline = (root / "app/src/main/cpp/src/Pipeline.hpp").read_text(encoding="utf-8")
    main_cpp = (root / "app/src/main/cpp/src/main.cpp").read_text(encoding="utf-8")
    cmake = (root / "app/src/main/cpp/CMakeLists.txt").read_text(encoding="utf-8")
    presets = (root / "app/src/main/cpp/CMakePresets.json").read_text(encoding="utf-8")

    require('applicationId = "io.github.xororz.localdream.s24uharness"' in gradle, "H2 package id missing")
    require('versionCode = 7402' in gradle, "H2 versionCode missing")
    require('versionName = "2.8.1-s24u-h2"' in gradle, "H2 versionName missing")
    require('signingConfig = signingConfigs.getByName("release")' in gradle, "stable debug signing config missing")
    require("S24U Image Harness" in strings, "H2 app name missing")

    require("S24U HARNESS · PURE RAW" in screen, "PURE RAW trace card missing")
    require('if (isFirstRun) "" else prefs.prompt' in screen, "first-run positive prompt is not PURE RAW")
    require('if (isFirstRun) "" else prefs.negativePrompt' in screen, "first-run negative prompt is not PURE RAW")
    require('promptField.replaceText("")' in screen, "reset positive prompt is not PURE RAW")
    require('negativePromptField.replaceText("")' in screen, "reset negative prompt is not PURE RAW")
    require("POS CHUNKS" in screen and "NEG CHUNKS" in screen, "long-prompt chunk trace missing")

    require("kS24uClipChunkLen = 77" in text_encoder, "fixed CLIP chunk size changed")
    require("kS24uClipContentTokens = 75" in text_encoder, "75-token content chunk missing")
    require("kS24uClipChunks = 4" in text_encoder, "four-chunk limit missing")
    require("kS24uClipEffectiveMaxLength" in text_encoder, "effective long prompt maximum missing")
    require("splitPromptChunks" in text_encoder, "native prompt chunk splitter missing")
    require("prefixBytesWithinBudget" in text_encoder, "token-aware split boundary missing")
    require("processPromptPair(" in pipeline, "existing fixed-shape prompt encoder not reused")
    require("encodePromptChunks" in pipeline, "multi-chunk conditioning path missing")
    require("std::vector<Conditioning> conds" in pipeline, "multi-conditioning generation state missing")
    require("for (auto &chunk_cond : conds)" in pipeline, "per-chunk UNet loop missing")
    require("noise_pred = xt::eval(noise_pred / (float)conds.size())" in pipeline,
            "chunk noise-prediction fusion missing")
    require("kS24uClipEffectiveMaxLength" in main_cpp, "/tokenize is not exposing expanded prompt budget")

    # Hard invariant: H2 long prompt must never enlarge the individual CLIP/QNN graph shape.
    require("processPromptPair(chunk_prompt, chunk_negative, kS24uClipChunkLen)" in pipeline,
            "chunk encoder does not pin every call to 77")
    require("processWeightedPrompt(positive, kS24uClipEffectiveMaxLength)" not in text_encoder,
            "single oversized CLIP call detected")

    require('getenv("QNN_SDK_ROOT")' in cmake, "CI-selectable QAIRT root missing")
    require('/data/android-ndk-r28' not in presets, "hard-coded local Android NDK path remains")

    print("H2_SOURCE_CONTRACT_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
