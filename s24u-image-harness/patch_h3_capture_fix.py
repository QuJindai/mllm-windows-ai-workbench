#!/usr/bin/env python3
from pathlib import Path
import sys


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: patch_h3_capture_fix.py <h3-patched-local-dream-root>", file=sys.stderr)
        return 2

    root = Path(sys.argv[1]).resolve()
    path = root / "app/src/main/cpp/src/main.cpp"
    text = path.read_text(encoding="utf-8")

    old = '  svr.Post("/generate", [pipeline](const httplib::Request &request,'
    new = '  svr.Post("/generate", [pipeline, text_encoder](const httplib::Request &request,'
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"H3 outer lambda capture: expected one match, found {count}")

    text = text.replace(old, new, 1)
    path.write_text(text, encoding="utf-8")
    print("H3_TEXT_ENCODER_OUTER_CAPTURE_FIX_APPLIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
