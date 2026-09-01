#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

import patch_h5


def fix_h5_runtime_contract(root: Path) -> None:
    pipeline = root / "app/src/main/cpp/src/Pipeline.hpp"
    text = pipeline.read_text(encoding="utf-8")
    if "#include <limits>" not in text:
        anchor = "#include <iostream>\n"
        if text.count(anchor) != 1:
            raise RuntimeError("H5 <limits>: include anchor not unique")
        text = text.replace(anchor, anchor + "#include <limits>\n", 1)
    pipeline.write_text(text, encoding="utf-8")

    css = root / "app/src/main/assets/s24u_microscope/microscope.css"
    text = css.read_text(encoding="utf-8")
    replacements = {
        "--primary:#4285f4;": "--primary: #4285f4;",
        "--page:#f7f7fa;": "--page: #f7f7fa;",
    }
    for old, new in replacements.items():
        if text.count(old) != 1:
            raise RuntimeError(f"H5 CSS normalization: expected one {old!r}")
        text = text.replace(old, new, 1)
    css.write_text(text, encoding="utf-8")

    js = root / "app/src/main/assets/s24u_microscope/microscope.js"
    text = js.read_text(encoding="utf-8")
    old = "window.S24UMicroscope={update(snapshot){pendingSnapshot=snapshot||{};if(!rafId)rafId=requestAnimationFrame(flush);}};"
    new = "window.S24UMicroscope={update(snapshot){pendingSnapshot=Object.assign({},pendingSnapshot||{},snapshot||{});if(!rafId)rafId=requestAnimationFrame(flush);}};"
    if text.count(old) != 1:
        raise RuntimeError("H5 partial-update merge: update() anchor not unique")
    text = text.replace(old, new, 1)
    js.write_text(text, encoding="utf-8")


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: patch_h5_v2.py <h4-patched-local-dream-root>", file=sys.stderr)
        return 2
    rc = patch_h5.main()
    if rc != 0:
        return rc
    root = Path(sys.argv[1]).resolve()
    fix_h5_runtime_contract(root)
    print("S24U_IMAGE_HARNESS_H5_V2_RUNTIME_FIXES_APPLIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
