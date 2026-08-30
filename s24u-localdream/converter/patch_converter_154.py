#!/usr/bin/env python3
"""Patch one exact Local Dream SDXL converter kit for 154-token UNet context."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

EXPECTED_SHA = {
    "export_onnx_sdxl.py": "8a074f67d00ce771dd2aac48f188c04883f51f783d9dab75a9cd6a3c77de3963",
    "prepare_data_sdxl.py": "130d4a8238ea85bad7f6867f4af13ea02cd316fef3f6377945e6032b0860cb9a",
    "gen_quant_data_sdxl.py": "ec99f7916724361d9dd133b7e46c84696acc6fc5f9a5d01d8ba916120dd7277e",
    "convert_all_sdxl.sh": "a00e3f87664f4a2ed1903af4f777feb2eba341a3a9b76940b6de5e0bffd052bc",
}


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def locate(root: Path, name: str) -> Path:
    hits = [p for p in root.rglob(name) if p.is_file()]
    if len(hits) != 1:
        raise RuntimeError(f"{name}: expected one file, found {len(hits)}")
    path = hits[0]
    got = digest(path)
    expected = EXPECTED_SHA[name]
    if got != expected:
        raise RuntimeError(f"{name}: SHA mismatch {got}, expected {expected}")
    return path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("root", type=Path)
    args = ap.parse_args()
    root = args.root.resolve()

    export_path = locate(root, "export_onnx_sdxl.py")
    prep_path = locate(root, "prepare_data_sdxl.py")
    quant_path = locate(root, "gen_quant_data_sdxl.py")
    all_path = locate(root, "convert_all_sdxl.sh")

    export = export_path.read_text(encoding="utf-8")
    export = replace_once(
        export,
        "            torch.randn(1, 77, 2048),",
        "            torch.randn(1, 154, 2048),  # S24U two-CLIP-window context",
        "UNet ONNX context shape",
    )
    # Explicit regression guard: the CLIP graphs are intentionally still 77.
    if "torch.randn(1, 77, 768)" not in export or "torch.randn(1, 77, 1280)" not in export:
        raise RuntimeError("CLIP 77-token export anchors were unexpectedly changed")
    export_path.write_text(export, encoding="utf-8")

    prep = prep_path.read_text(encoding="utf-8")
    prep = replace_once(
        prep,
        "import torch\n",
        "import torch\n\nS24U_TEXT_SEQ_LEN = 154\n",
        "prepare-data constant",
    )
    prep = replace_once(
        prep,
        "    prompt_embeds = torch.cat([prompt_embeds_1_hidden, prompt_embeds_2_hidden], dim=-1)\n",
        "    prompt_embeds = torch.cat([prompt_embeds_1_hidden, prompt_embeds_2_hidden], dim=-1)\n"
        "    # Calibration must match the static QNN UNet graph. The mobile runtime\n"
        "    # evaluates two independent 77-token CLIP windows and concatenates the\n"
        "    # hidden states; for calibration, duplicate the representative 77-token\n"
        "    # distribution so the quantizer observes the exact [B,154,2048] shape.\n"
        "    prompt_embeds = torch.cat([prompt_embeds, prompt_embeds], dim=1)\n"
        "    assert prompt_embeds.shape[1] == S24U_TEXT_SEQ_LEN\n",
        "prepare-data UNet context expansion",
    )
    prep_path.write_text(prep, encoding="utf-8")

    quant = quant_path.read_text(encoding="utf-8")
    quant = replace_once(
        quant,
        "    text_embed = text_embed.astype(np.float32)\n",
        "    text_embed = text_embed.astype(np.float32)\n"
        "    if text_embed.ndim != 3 or text_embed.shape[1] != 154:\n"
        "        raise ValueError(f\"expected UNet text context [B,154,2048], got {text_embed.shape}\")\n",
        "quantization shape assertion",
    )
    quant_path.write_text(quant, encoding="utf-8")

    allsh = all_path.read_text(encoding="utf-8")
    allsh = replace_once(
        allsh,
        "bash scripts/convert_unet_sdxl.sh\n",
        "bash scripts/convert_unet_sdxl.sh\n\n"
        "# Runtime capability markers consumed by the S24U APK.\n"
        "touch \"output/qnn_models_sdxl$SUFFIX/SDXL\"\n"
        "printf '154\\n' > \"output/qnn_models_sdxl$SUFFIX/TEXT_SEQ_LEN\"\n",
        "model capability markers",
    )
    all_path.write_text(allsh, encoding="utf-8")

    print("PATCHED export_onnx_sdxl.py: UNet context 77 -> 154")
    print("PATCHED prepare_data_sdxl.py: calibration context -> 154")
    print("PATCHED gen_quant_data_sdxl.py: enforce calibration shape")
    print("PATCHED convert_all_sdxl.sh: SDXL + TEXT_SEQ_LEN markers")
    print("CONVERTER_154_PATCH_APPLY=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
