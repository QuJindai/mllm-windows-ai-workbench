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
        print("usage: test_h6r4_token_truth_contract.py <h6r3-patched-root>", file=sys.stderr)
        return 2
    root = Path(sys.argv[1]).resolve()
    gradle = (root / "app/build.gradle.kts").read_text(encoding="utf-8")
    text_encoder = (root / "app/src/main/cpp/src/TextEncoder.hpp").read_text(encoding="utf-8")
    pipeline = (root / "app/src/main/cpp/src/Pipeline.hpp").read_text(encoding="utf-8")
    main_cpp = (root / "app/src/main/cpp/src/main.cpp").read_text(encoding="utf-8")
    service = (root / "app/src/main/java/io/github/xororz/localdream/service/BackgroundGenerationService.kt").read_text(encoding="utf-8")
    screen = (root / "app/src/main/java/io/github/xororz/localdream/ui/screens/ModelRunScreen.kt").read_text(encoding="utf-8")
    js = (root / "app/src/main/assets/s24u_microscope/microscope.js").read_text(encoding="utf-8")

    require(gradle, "versionCode = 7410", "H6R4 versionCode")
    require(gradle, 'versionName = "2.8.1-s24u-h6r4"', "H6R4 versionName")

    # Token-preserving inference must parse and tokenize once, then slice the
    # weighted token stream directly. Re-rendering escaped chunk text and
    # tokenizing it again is exactly what produced the phone-observed 90 -> 91.
    require(text_encoder, "processWeightedPromptChunks", "direct weighted-token chunker")
    require(text_encoder, "processPromptPairChunks", "direct prompt-pair chunker")
    require(text_encoder, "content_ids", "exact unpadded content token ids")
    require(text_encoder, "content_weights", "exact token weights")
    require(pipeline, "processPromptPairChunks", "pipeline uses direct processed chunks")
    forbid(pipeline, "splitPromptChunks(req.prompt)", "no positive text re-tokenization in inference")
    forbid(pipeline, "splitPromptChunks(req.negative_prompt)", "no negative text re-tokenization in inference")
    require(pipeline, "positive_content_tokens", "conditioning exact positive chunk count")
    require(pipeline, "negative_content_tokens", "conditioning exact negative chunk count")
    forbid(pipeline, "promptContentTokenCount(fusion_pos_chunks[j])", "fusion does not re-tokenize reconstructed positive text")
    forbid(pipeline, "promptContentTokenCount(fusion_neg_chunks[j])", "fusion does not re-tokenize reconstructed negative text")

    # Runtime evidence must prove preservation, not just display a count.
    for needle in (
        '"positive_chunk_token_ids"', '"negative_chunk_token_ids"',
        '"positive_token_preserved"', '"negative_token_preserved"',
    ):
        require(main_cpp, needle, f"native token-truth trace {needle}")
    require(service, "positiveTokenPreserved", "Android positive preservation flag")
    require(service, "negativeTokenPreserved", "Android negative preservation flag")
    require(screen, 'put("positive_token_preserved"', "WebView positive preservation payload")
    require(js, "TOKEN PRESERVATION", "human-readable preservation status")

    # Guidance truth: prompt presence, CLIP execution and effective guidance
    # are distinct facts. 'negative_encoded' alone is too strong a label.
    require(service, "negativePromptPresent", "negative prompt presence fact")
    require(service, "negativeClipExecuted", "negative CLIP execution fact")
    require(service, "negativeUnetExecuted", "negative UNet execution fact")
    require(js, "Negative CLIP", "negative CLIP truth UI")
    require(js, "Negative UNet", "negative UNet truth UI")

    # Runtime graph must use cumulative native observations. Formula-derived
    # expected counts may remain, but must never be presented as observed.
    for needle in (
        "observed_unet_passes", "observed_scheduler_calls", "observed_vae_decodes",
        "observed_clip_passes", "unet_total_ms", "scheduler_total_ms",
        "vae_total_ms", "clip_total_ms", "accounted_ms", "unattributed_ms",
    ):
        require(pipeline + main_cpp + service + screen + js, needle, f"runtime truth field {needle}")
    require(js, "observed_calls", "runtime graph observed calls")
    require(js, "expected_calls", "runtime graph expected calls")
    require(js, "Unattributed", "runtime graph unattributed time")
    forbid(js, "const clipCalls=k,unetCalls=activeChunks*steps", "old JS-derived call truth")

    # 0-frame decoded preview should collapse to a compact NOT EXECUTED state.
    require(js, "NOT EXECUTED", "compact VAE non-execution state")

    print("H6R4_TOKEN_TRUTH_CONTRACT_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
