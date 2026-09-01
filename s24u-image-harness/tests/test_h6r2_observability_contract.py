#!/usr/bin/env python3
from pathlib import Path
import sys


def require(text: str, needle: str, label: str) -> None:
    if needle not in text:
        raise AssertionError(f"{label}: missing {needle!r}")


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: test_h6r2_observability_contract.py <local-dream-root>", file=sys.stderr)
        return 2
    root = Path(sys.argv[1])
    gradle = (root / "app/build.gradle.kts").read_text(encoding="utf-8")
    screen = (root / "app/src/main/java/io/github/xororz/localdream/ui/screens/ModelRunScreen.kt").read_text(encoding="utf-8")
    html = (root / "app/src/main/assets/s24u_microscope/index.html").read_text(encoding="utf-8")
    js = (root / "app/src/main/assets/s24u_microscope/microscope.js").read_text(encoding="utf-8")

    require(gradle, "versionCode = 7408", "H6R2 versionCode")
    require(gradle, 'versionName = "2.8.1-s24u-h6r2"', "H6R2 versionName")
    require(screen, "S24U_H6R2_OBSERVABILITY_FALLBACK", "H6R2 DEX marker")

    # Process view must remain truthful: prefer real VAE previews, otherwise
    # use the already-captured scheduler latent maps. Never claim fallback is VAE.
    require(html, "PROCESS EVIDENCE", "process evidence heading")
    require(html, "自动回退显示同一步真实 scheduler latent", "truthful lowram explanation")
    require(js, "usingLatentFallback=previews.length===0 && latents.length>0", "lowram fallback selection")
    require(js, "const processFrames=usingLatentFallback?latents:previews", "process fallback source")
    require(js, "LATENT FALLBACK", "fallback metadata label")
    require(js, "真实 scheduler latent · 非 VAE decode", "fallback semantic guard")
    require(js, "previews.length?previews:latents", "process scrub fallback")

    # A single chunk is mathematically identical to the fused prediction.
    # Avoid presenting the resulting all-zero map as an unexplained black box.
    require(js, "const singleChunk=int(sample.chunk_count,1)===1", "single chunk detection")
    require(js, "ε̄ₜ = εₜ⁽¹⁾", "single chunk formula explanation")
    require(js, "不再显示没有信息量的全黑图", "black-map explanation")

    # Cross-attention remains unavailable and must be shown as a capability
    # boundary rather than an apparent rendering failure.
    require(html, "ATTRIBUTION · CAPABILITY", "attribution capability heading")
    require(html, "当前不可观测：Cross-attention 未导出", "cross attention capability state")
    require(html, "这是当前 QNN 编译图的能力缺口，不是页面加载失败", "cross attention non-bug explanation")

    print("H6R2_OBSERVABILITY_CONTRACT_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
