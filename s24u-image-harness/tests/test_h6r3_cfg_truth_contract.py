#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


def require(text: str, needle: str, label: str) -> None:
    if needle not in text:
        raise AssertionError(f"{label}: missing {needle!r}")


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: test_h6r3_cfg_truth_contract.py <patched-local-dream-root>", file=sys.stderr)
        return 2

    root = Path(sys.argv[1]).resolve()
    gradle = (root / "app/build.gradle.kts").read_text(encoding="utf-8")
    pipeline = (root / "app/src/main/cpp/src/Pipeline.hpp").read_text(encoding="utf-8")
    main_cpp = (root / "app/src/main/cpp/src/main.cpp").read_text(encoding="utf-8")
    service = (root / "app/src/main/java/io/github/xororz/localdream/service/BackgroundGenerationService.kt").read_text(encoding="utf-8")
    screen = (root / "app/src/main/java/io/github/xororz/localdream/ui/screens/ModelRunScreen.kt").read_text(encoding="utf-8")
    js = (root / "app/src/main/assets/s24u_microscope/microscope.js").read_text(encoding="utf-8")

    require(gradle, "versionCode = 7409", "H6R3 versionCode")
    require(gradle, 'versionName = "2.8.1-s24u-h6r3"', "H6R3 versionName")
    require(screen, 'put("h6r3_marker", "S24U_H6R3_SEMANTIC_FIDELITY")', "H6R3 DEX marker")

    for field in (
        "cfg_value",
        "negative_encoded",
        "positive_effective_weight",
        "negative_effective_weight",
    ):
        require(pipeline, field, f"native {field}")
        require(main_cpp, f'"{field}"', f"serialized {field}")

    # Effective negative guidance is a magnitude. For the QNN cfg=1 fast path
    # the unconditional UNet call is skipped, therefore the value must be 0.
    require(pipeline, "skip_uncond ? 0.0f", "cfg=1 zero negative effective weight")
    require(pipeline, "std::max(req.cfg - 1.0f, 0.0f)", "guided negative magnitude")

    require(service, "cfgValue", "Android cfg value")
    require(service, "negativeEncoded", "Android negative encoded")
    require(service, "positiveEffectiveWeight", "Android positive effective weight")
    require(service, "negativeEffectiveWeight", "Android negative effective weight")

    require(screen, 'put("cfg_value", microscope.cfgValue.toDouble())', "WebView cfg payload")
    require(screen, 'put("negative_effective_weight", microscope.negativeEffectiveWeight.toDouble())', "WebView negative weight payload")
    require(js, "negative_effective_weight", "CFG runtime UI data")
    require(js, "NEG effective", "CFG runtime UI wording")
    require(js, "已编码，但本轮不参与最终 guidance", "cfg=1 negative explanation")

    print("H6R3_CFG_TRUTH_CONTRACT_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
