#!/usr/bin/env python3
"""Extract narrow, reviewable context around SDXL UNet/context-shape sites.

The official converter kit is not versioned in GitHub. This script turns the
pinned ZIP into a small evidence file so the 154-token patch can be written
against observed code rather than guessed directory/layout assumptions.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

TARGETS = {
    "export_onnx_sdxl.py": [
        "class UNetWrapper",
        "encoder_hidden_states",
        "torch.randn",
        "torch.onnx.export",
    ],
    "gen_quant_data_sdxl.py": [
        "encoder_hidden_states",
        "np.",
        "shape",
        "names=",
    ],
    "prepare_data_sdxl.py": [
        "encoder_hidden_states=prompt_embeds",
        "prompt_embeds",
        "np.save",
        "torch.save",
    ],
    "convert_unet_sdxl.sh": ["qnn", "input", "onnx", "quant"],
    "convert_all_sdxl.sh": ["convert_unet", "sdxl", "python"],
}


def locate(root: Path, basename: str) -> Path:
    hits = [p for p in root.rglob(basename) if p.is_file()]
    if len(hits) != 1:
        raise RuntimeError(f"{basename}: expected 1 file, found {len(hits)}")
    return hits[0]


def blocks(lines: list[str], needles: list[str], radius: int = 8) -> list[dict]:
    ranges: list[tuple[int, int]] = []
    for i, line in enumerate(lines):
        if any(n in line for n in needles):
            ranges.append((max(0, i - radius), min(len(lines), i + radius + 1)))
    merged: list[tuple[int, int]] = []
    for start, end in ranges:
        if merged and start <= merged[-1][1] + 2:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    out = []
    for start, end in merged:
        out.append(
            {
                "start_line": start + 1,
                "end_line": end,
                "lines": [
                    {"line": idx + 1, "text": lines[idx]}
                    for idx in range(start, end)
                ],
            }
        )
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("root", type=Path)
    ap.add_argument("--json", type=Path, required=True)
    ap.add_argument("--text", type=Path, required=True)
    args = ap.parse_args()
    root = args.root.resolve()

    evidence = {"schema": 1, "files": {}}
    text_parts = []
    for basename, needles in TARGETS.items():
        path = locate(root, basename)
        rel = path.relative_to(root).as_posix()
        lines = path.read_text(encoding="utf-8").splitlines()
        bs = blocks(lines, needles)
        evidence["files"][basename] = {"path": rel, "blocks": bs}
        text_parts.append(f"===== {rel} =====")
        for block in bs:
            text_parts.append(f"--- lines {block['start_line']}-{block['end_line']} ---")
            for item in block["lines"]:
                text_parts.append(f"{item['line']:04d}: {item['text']}")
        text_parts.append("")

    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    args.text.write_text("\n".join(text_parts), encoding="utf-8")
    print(f"CONVERTER_CONTEXT=PASS files={len(evidence['files'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
