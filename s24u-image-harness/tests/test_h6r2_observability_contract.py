#!/usr/bin/env python3
from pathlib import Path
import sys


def require(text: str, needle: str, label: str) -> None:
    if needle not in text:
        raise AssertionError(f"{label}: missing {needle!r}")


def require_any(text: str, needles: tuple[str, ...], label: str) -> None:
    if not any(needle in text for needle in needles):
        raise AssertionError(f"{label}: missing one of {needles!r}")


def forbid(text: str, needle: str, label: str) -> None:
    if needle in text:
        raise AssertionError(f"{label}: forbidden {needle!r}")


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: test_h6r2_observability_contract.py <local-dream-root>", file=sys.stderr)
        return 2
    root = Path(sys.argv[1])
    gradle = (root / "app/build.gradle.kts").read_text(encoding="utf-8")
    screen = (root / "app/src/main/java/io/github/xororz/localdream/ui/screens/ModelRunScreen.kt").read_text(encoding="utf-8")
    html = (root / "app/src/main/assets/s24u_microscope/index.html").read_text(encoding="utf-8")
    js = (root / "app/src/main/assets/s24u_microscope/microscope.js").read_text(encoding="utf-8")

    require_any(gradle, ("versionCode = 7408", "versionCode = 7409"), "H6R2-compatible versionCode")
    require_any(
        gradle,
        ('versionName = "2.8.1-s24u-h6r2"', 'versionName = "2.8.1-s24u-h6r3"'),
        "H6R2-compatible versionName",
    )
    require(screen, "S24U_H6R2_OBSERVABILITY_FALLBACK", "H6R2 DEX marker")

    dynamics_enabled = "PROCESS DYNAMICS" in html and "renderProcessDynamics" in js
    if not dynamics_enabled:
        # Historical H6R2 behavior remains valid through early H6R3 tasks until
        # Task 4 actually replaces it. Package version alone is not a capability
        # marker because H6R3 bumps to 7409 at Task 2.
        require(html, "PROCESS EVIDENCE", "H6R2 process evidence heading")
        require(html, "自动回退显示同一步真实 scheduler latent", "H6R2 lowram explanation")
        require(js, "usingLatentFallback=previews.length===0 && latents.length>0", "H6R2 lowram fallback selection")
        require(js, "const processFrames=usingLatentFallback?latents:previews", "H6R2 process fallback source")
        require(js, "LATENT FALLBACK", "H6R2 fallback metadata label")
        require(js, "真实 scheduler latent · 非 VAE decode", "H6R2 fallback semantic guard")
    else:
        # H6R3 Task 4 removes the duplicate view: Process = Δlatent dynamics;
        # the old 2x2 contact sheet remains only under Latent State.
        require(html, "PROCESS DYNAMICS", "H6R3 process dynamics heading")
        require(html, "DECODED PREVIEW", "H6R3 decoded preview boundary")
        require(js, "renderProcessDynamics", "H6R3 dynamics renderer")
        forbid(js, "const processFrames=usingLatentFallback?latents:previews", "no duplicate H6R2 fallback")
        forbid(js, "showFrame('process',previews.length?previews:latents", "no latent-as-decoded preview")

    require(js, "const singleChunk=int(sample.chunk_count,1)===1", "single chunk detection")
    require(js, "ε̄ₜ = εₜ⁽¹⁾", "single chunk formula explanation")
    require(js, "不再显示没有信息量的全黑图", "black-map explanation")

    require(html, "ATTRIBUTION · CAPABILITY", "attribution capability heading")
    require_any(
        html,
        ("当前不可观测：Cross-attention 未导出", "Production QNN 图未导出"),
        "cross attention capability state",
    )
    require_any(
        html,
        ("这是当前 QNN 编译图的能力缺口，不是页面加载失败", "Debug UNet Graph"),
        "cross attention non-bug explanation",
    )

    print("H6R2_OBSERVABILITY_CONTRACT_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
