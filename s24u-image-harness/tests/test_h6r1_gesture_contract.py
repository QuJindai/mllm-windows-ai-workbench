#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


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
        print("usage: test_h6r1_gesture_contract.py <patched-local-dream-root>", file=sys.stderr)
        return 2

    root = Path(sys.argv[1]).resolve()
    gradle = (root / "app/build.gradle.kts").read_text(encoding="utf-8")
    screen = (
        root
        / "app/src/main/java/io/github/xororz/localdream/ui/screens/ModelRunScreen.kt"
    ).read_text(encoding="utf-8")
    css = (root / "app/src/main/assets/s24u_microscope/microscope.css").read_text(
        encoding="utf-8"
    )
    js = (root / "app/src/main/assets/s24u_microscope/microscope.js").read_text(
        encoding="utf-8"
    )

    # H6R1 behavior must remain present in later package revisions. Package
    # version bumps are allowed, but none of the gesture arbitration assertions
    # below are relaxed.
    require_any(
        gradle,
        ("versionCode = 7407", "versionCode = 7408", "versionCode = 7409"),
        "H6R1-compatible versionCode",
    )
    require_any(
        gradle,
        (
            'versionName = "2.8.1-s24u-h6r1"',
            'versionName = "2.8.1-s24u-h6r2"',
            'versionName = "2.8.1-s24u-h6r3"',
        ),
        "H6R1-compatible versionName",
    )

    require(screen, "pageCount = { 4 }", "four-page pager retained")
    require(
        screen,
        "userScrollEnabled = pagerState.currentPage != 3",
        "microscope parent pager disabled only on page 4",
    )
    require(
        screen,
        'put("h6_marker", "S24U_H6_CONDITIONING_INFLUENCE")',
        "H6 runtime marker retained",
    )
    require(
        screen,
        'put("h6r1_marker", "S24U_H6R1_GESTURE_ARBITRATION")',
        "H6R1 compiled gesture marker",
    )

    require(css, "touch-action:pan-y", "WebView vertical gesture dominance")
    require(css, "overscroll-behavior-x:none", "horizontal overscroll suppression")
    require(
        css,
        ".scrubber{width:100%;accent-color:var(--primary);margin:16px 0 6px;touch-action:pan-x}",
        "range sliders keep horizontal drag",
    )
    require(
        css,
        "overflow-x:auto;padding:18px 2px 8px;scrollbar-width:none;touch-action:pan-x",
        "pipeline keeps intentional horizontal pan",
    )
    require(
        css,
        "overflow-x:auto;padding-top:12px;scrollbar-width:none;touch-action:pan-x",
        "thumbnail strip keeps intentional horizontal pan",
    )

    for token in ("touchstart", "touchmove", "pointerdown", "pointermove"):
        forbid(js, token, "no custom JS swipe recognizer")

    print("H6R1_GESTURE_CONTRACT_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
