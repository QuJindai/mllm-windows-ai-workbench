#!/usr/bin/env python3
from pathlib import Path
import sys


def require(text: str, needle: str, label: str) -> None:
    if needle not in text:
        raise AssertionError(f"{label}: missing {needle!r}")


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: test_h6r5r1_history_carousel_contract.py <patched-root>", file=sys.stderr)
        return 2
    root = Path(sys.argv[1]).resolve()
    gradle = (root / "app/build.gradle.kts").read_text(encoding="utf-8")
    history = (root / "app/src/main/java/io/github/xororz/localdream/ui/screens/HistoryScreen.kt").read_text(encoding="utf-8")
    overlay = (root / "app/src/main/java/io/github/xororz/localdream/ui/components/ZoomableImageOverlay.kt").read_text(encoding="utf-8")

    require(gradle, "versionCode = 7412", "H6R5R1 versionCode")
    require(gradle, 'versionName = "2.8.1-s24u-h6r5r1"', "H6R5R1 versionName")

    for needle in (
        "previewIds", "previewIndex", "previewLoading", "queryIds(historyFilter)",
        "getItems(listOf(targetId))", "navigatePreview", "canNavigatePrevious",
        "canNavigateNext", "navigationPosition", "onPrevious", "onNext",
        "S24U_H6R5R1_HISTORY_CAROUSEL",
    ):
        require(history + overlay, needle, f"history carousel evidence {needle}")

    require(overlay, "detectHorizontalDragGestures", "1x horizontal swipe navigation")
    require(overlay, "scale <= 1.01f", "swipe only at base zoom")
    require(history, "remainingIds", "delete keeps carousel sequence")
    require(history, "newIndex = removedIndex.coerceAtMost", "delete continues to adjacent image")
    require(history, "previewItem = item.copy(favorite = !item.favorite)", "favorite keeps current preview")

    print("H6R5R1_HISTORY_CAROUSEL_CONTRACT_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
