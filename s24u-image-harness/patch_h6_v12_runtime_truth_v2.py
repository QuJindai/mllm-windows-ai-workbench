#!/usr/bin/env python3
from __future__ import annotations

import patch_h6_v12_runtime_truth as base

_original_replace_once = base.replace_once


def stable_replace_once(text: str, old: str, new: str, label: str) -> str:
    if label == "runtime CLIP cumulative truth":
        needle = "    auto clip_dur = elapsedMs(clip_start);\n"
        replacement = (
            needle
            + "    clip_total_ms = clip_dur;\n"
            + "    observed_clip_passes = static_cast<int>(std::count_if(\n"
            + "        conds.begin(), conds.end(), [](const Conditioning &c) {\n"
            + "          return c.positive_clip_executed || c.negative_clip_executed;\n"
            + "        }));\n"
        )
        return _original_replace_once(text, needle, replacement, label)
    if label == "runtime final VAE accumulate":
        needle = "    auto vae_dec_dur = elapsedMs(vae_dec_start);\n"
        replacement = (
            needle
            + "    observed_vae_decodes++;\n"
            + "    vae_total_ms += vae_dec_dur;\n"
        )
        return _original_replace_once(text, needle, replacement, label)
    return _original_replace_once(text, old, new, label)


def main() -> int:
    base.replace_once = stable_replace_once
    rc = base.main()
    if rc == 0:
        print("S24U_IMAGE_HARNESS_H6R4_RUNTIME_TRUTH_V2_APPLIED")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
