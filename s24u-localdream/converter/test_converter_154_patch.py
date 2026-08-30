#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path


def one(root: Path, name: str) -> Path:
    hits = [p for p in root.rglob(name) if p.is_file()]
    if len(hits) != 1:
        raise AssertionError(f"{name}: expected one file, found {len(hits)}")
    return hits[0]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("root", type=Path)
    ap.add_argument("--expect", choices=["baseline", "patched"], required=True)
    a = ap.parse_args()
    root = a.root.resolve()

    export = one(root, "export_onnx_sdxl.py").read_text(encoding="utf-8")
    prep = one(root, "prepare_data_sdxl.py").read_text(encoding="utf-8")
    quant = one(root, "gen_quant_data_sdxl.py").read_text(encoding="utf-8")
    allsh = one(root, "convert_all_sdxl.sh").read_text(encoding="utf-8")

    # CLIP graphs must remain fixed 77-token graphs in both modes. The APK
    # executes each CLIP graph once per chunk and concatenates hidden states.
    assert "torch.randn(1, 77, 768)" in export
    assert "torch.randn(1, 77, 1280)" in export

    if a.expect == "baseline":
        assert "torch.randn(1, 77, 2048)" in export
        assert "torch.randn(1, 154, 2048)" not in export
        assert "S24U_TEXT_SEQ_LEN = 154" not in prep
        assert "TEXT_SEQ_LEN" not in allsh
        print("CONVERTER_BASELINE=PASS")
        return 0

    assert "torch.randn(1, 154, 2048)" in export
    assert "torch.randn(1, 77, 2048)" not in export
    assert "S24U_TEXT_SEQ_LEN = 154" in prep
    assert "prompt_embeds = torch.cat([prompt_embeds, prompt_embeds], dim=1)" in prep
    assert "text_embed.shape[1] != 154" in quant
    assert "TEXT_SEQ_LEN" in allsh and "154" in allsh
    assert "/SDXL" in allsh
    print("CONVERTER_154_PATCH=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
