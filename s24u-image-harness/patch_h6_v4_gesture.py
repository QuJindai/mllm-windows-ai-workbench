#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one literal match, found {count}")
    return text.replace(old, new, 1)


def patch_gradle(root: Path) -> None:
    path = root / "app/build.gradle.kts"
    text = path.read_text(encoding="utf-8")
    text = replace_once(text, "versionCode = 7406", "versionCode = 7407", "H6R1 versionCode")
    text = replace_once(
        text,
        'versionName = "2.8.1-s24u-h6"',
        'versionName = "2.8.1-s24u-h6r1"',
        "H6R1 versionName",
    )
    path.write_text(text, encoding="utf-8")


def patch_screen(root: Path) -> None:
    path = root / "app/src/main/java/io/github/xororz/localdream/ui/screens/ModelRunScreen.kt"
    text = path.read_text(encoding="utf-8")

    pager_old = '''                HorizontalPager(
                    state = pagerState,
                    modifier = Modifier
'''
    pager_new = '''                HorizontalPager(
                    state = pagerState,
                    // S24U H6R1: the microscope is a vertically scrolling Android WebView.
                    // While page 4 is active, do not let the parent pager compete for a
                    // diagonal gesture's horizontal component. Top tabs remain the
                    // deterministic navigation path out of the microscope.
                    userScrollEnabled = pagerState.currentPage != 3,
                    modifier = Modifier
'''
    text = replace_once(
        text,
        pager_old,
        pager_new,
        "H6R1 microscope/parent pager gesture arbitration",
    )

    marker_old = '            put("h6_marker", "S24U_H6_CONDITIONING_INFLUENCE")\n'
    marker_new = marker_old + '            put("h6r1_marker", "S24U_H6R1_GESTURE_ARBITRATION")\n'
    text = replace_once(text, marker_old, marker_new, "H6R1 compiled DEX marker")
    path.write_text(text, encoding="utf-8")


def patch_css(root: Path) -> None:
    path = root / "app/src/main/assets/s24u_microscope/microscope.css"
    text = path.read_text(encoding="utf-8")

    html_old = 'html,body{margin:0;background:var(--page);color:var(--text);font-family:system-ui,-apple-system,"Noto Sans SC","Segoe UI",sans-serif}'
    html_new = 'html,body{margin:0;background:var(--page);color:var(--text);font-family:system-ui,-apple-system,"Noto Sans SC","Segoe UI",sans-serif;touch-action:pan-y;overscroll-behavior-x:none}'
    text = replace_once(text, html_old, html_new, "H6R1 WebView vertical touch policy")

    scrub_old = '.scrubber{width:100%;accent-color:var(--primary);margin:16px 0 6px}'
    scrub_new = '.scrubber{width:100%;accent-color:var(--primary);margin:16px 0 6px;touch-action:pan-x}'
    text = replace_once(text, scrub_old, scrub_new, "H6R1 slider horizontal touch policy")

    pipeline_old = '.pipeline{display:flex;align-items:center;gap:8px;overflow-x:auto;padding:18px 2px 8px;scrollbar-width:none}'
    pipeline_new = '.pipeline{display:flex;align-items:center;gap:8px;overflow-x:auto;padding:18px 2px 8px;scrollbar-width:none;touch-action:pan-x}'
    text = replace_once(text, pipeline_old, pipeline_new, "H6R1 pipeline horizontal touch policy")

    thumbs_old = '.thumbs{display:flex;gap:8px;overflow-x:auto;padding-top:12px;scrollbar-width:none}'
    thumbs_new = '.thumbs{display:flex;gap:8px;overflow-x:auto;padding-top:12px;scrollbar-width:none;touch-action:pan-x}'
    text = replace_once(text, thumbs_old, thumbs_new, "H6R1 thumbs horizontal touch policy")

    path.write_text(text, encoding="utf-8")


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: patch_h6_v4_gesture.py <h6-v3-patched-local-dream-root>", file=sys.stderr)
        return 2
    root = Path(sys.argv[1]).resolve()
    patch_gradle(root)
    patch_screen(root)
    patch_css(root)
    print("S24U_IMAGE_HARNESS_H6R1_GESTURE_ARBITRATION_APPLIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
