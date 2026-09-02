#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one literal match, found {count}")
    return text.replace(old, new, 1)


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: patch_h6_v2.py <h6-patched-local-dream-root>", file=sys.stderr)
        return 2

    root = Path(sys.argv[1]).resolve()
    pipeline = root / "app/src/main/cpp/src/Pipeline.hpp"
    text = pipeline.read_text(encoding="utf-8")

    old = '''        emit_trace(influence_trace);
      }

      auto scheduler_start = std::chrono::high_resolution_clock::now();
'''
    new = '''        emit_trace(influence_trace);
      }
      // H6 V2: raw per-chunk predictions are only needed for influence
      // telemetry. Release their backing buffers before scheduler work so the
      // rest of this diffusion iteration carries only the fused prediction.
      chunk_predictions.clear();

      auto scheduler_start = std::chrono::high_resolution_clock::now();
'''
    text = replace_once(
        text,
        old,
        new,
        "H6 release per-step chunk tensors before scheduler",
    )
    pipeline.write_text(text, encoding="utf-8")
    print("S24U_IMAGE_HARNESS_H6_V2_MEMORY_RELEASE_APPLIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
