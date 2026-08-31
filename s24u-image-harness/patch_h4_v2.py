#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

import patch_h4


_ORIGINAL_REPLACE_ONCE = patch_h4.replace_once


def region_safe_replace_once(text: str, old: str, new: str, label: str) -> str:
    """Keep strict patching except for the known Event/Snapshot shared tail."""
    if label == "H4 event budget fields":
        count = text.count(old)
        if count != 2:
            raise RuntimeError(
                f"{label}: expected the H3 Event/Snapshot shared anchor twice, found {count}"
            )
        return text.replace(old, new, 1)
    return _ORIGINAL_REPLACE_ONCE(text, old, new, label)


def fix_visualizer_contract_and_formula(root: Path) -> None:
    path = root / "app/src/main/assets/s24u_microscope/microscope.js"
    text = path.read_text(encoding="utf-8")

    formula_old = "    const content = Math.max(posInput - 2, 0);"
    formula_new = "    const content = Math.max(posInput, 0);"
    if text.count(formula_old) != 1:
        raise RuntimeError(
            "H4 formula token-unit fix: expected exactly one content-token expression"
        )
    text = text.replace(formula_old, formula_new, 1)

    budget_old = '''  function budget(snapshot, prefix) {
    return {
      input: int(snapshot[`${prefix}_input_tokens`]),
      effective: int(snapshot[`${prefix}_effective_tokens`]),
      truncated: int(snapshot[`${prefix}_truncated_tokens`]),
      chunks: arr(snapshot[`${prefix}_chunk_tokens`]),
      texts: arr(snapshot[`${prefix}_chunks`]),
    };
  }
'''
    budget_new = '''  function budget(snapshot, prefix) {
    if (prefix === 'positive') {
      return {
        input: int(snapshot.positive_input_tokens),
        effective: int(snapshot.positive_effective_tokens),
        truncated: int(snapshot.positive_truncated_tokens),
        chunks: arr(snapshot.positive_chunk_tokens),
        texts: arr(snapshot.positive_chunks),
      };
    }
    return {
      input: int(snapshot.negative_input_tokens),
      effective: int(snapshot.negative_effective_tokens),
      truncated: int(snapshot.negative_truncated_tokens),
      chunks: arr(snapshot.negative_chunk_tokens),
      texts: arr(snapshot.negative_chunks),
    };
  }
'''
    if text.count(budget_old) != 1:
        raise RuntimeError(
            "H4 visualizer budget fix: expected exactly one dynamic budget helper"
        )
    text = text.replace(budget_old, budget_new, 1)
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
    fix_visualizer_contract_and_formula(root)
    print("S24U_IMAGE_HARNESS_H4_V2_REGION_FORMULA_AND_BUDGET_FIX_APPLIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
