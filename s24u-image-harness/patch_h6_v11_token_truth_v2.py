#!/usr/bin/env python3
from __future__ import annotations

import patch_h6_v11_token_truth as base


_original_replace_once = base.replace_once


def stable_replace_once(text: str, old: str, new: str, label: str) -> str:
    if label == "single conditioning CLIP execution facts":
        needle = "  encodeText(processed, !neg_hit, !pos_hit, cond);\n"
        replacement = (
            needle
            + "  cond.negative_clip_executed = !neg_hit;\n"
            + "  cond.positive_clip_executed = !pos_hit;\n"
        )
        return _original_replace_once(text, needle, replacement, label)
    return _original_replace_once(text, old, new, label)


def main() -> int:
    base.replace_once = stable_replace_once
    rc = base.main()
    if rc == 0:
        print("S24U_IMAGE_HARNESS_H6R4_TOKEN_TRUTH_V2_APPLIED")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
