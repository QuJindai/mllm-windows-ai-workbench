#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

import patch_h4


_ORIGINAL_REPLACE_ONCE = patch_h4.replace_once


def region_safe_replace_once(text: str, old: str, new: str, label: str) -> str:
    """Keep strict patching except for the known Event/Snapshot shared tail.

    H3 deliberately gives MicroscopeEvent and MicroscopeSnapshot the same
    trailing positiveChunks/negativeChunks fields. H4 extends Event first and
    Snapshot second, so this one anchor legitimately occurs twice before the
    first replacement. Replacing only the first occurrence targets Event;
    Snapshot remains available for the explicitly unique snapshot anchor.
    """
    if label == "H4 event budget fields":
        count = text.count(old)
        if count != 2:
            raise RuntimeError(
                f"{label}: expected the H3 Event/Snapshot shared anchor twice, found {count}"
            )
        return text.replace(old, new, 1)
    return _ORIGINAL_REPLACE_ONCE(text, old, new, label)


def fix_formula_token_units(root: Path) -> None:
    path = root / "app/src/main/assets/s24u_microscope/microscope.js"
    text = path.read_text(encoding="utf-8")
    old = "    const content = Math.max(posInput - 2, 0);"
    new = "    const content = Math.max(posInput, 0);"
    if text.count(old) != 1:
        raise RuntimeError(
            "H4 formula token-unit fix: expected exactly one content-token expression"
        )
    text = text.replace(old, new, 1)
    path.write_text(text, encoding="utf-8")


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: patch_h4_v2.py <h3-patched-local-dream-root>", file=sys.stderr)
        return 2

    patch_h4.replace_once = region_safe_replace_once
    rc = patch_h4.main()
    if rc != 0:
        return rc

    root = Path(sys.argv[1]).resolve()
    fix_formula_token_units(root)
    print("S24U_IMAGE_HARNESS_H4_V2_REGION_AND_FORMULA_FIX_APPLIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
