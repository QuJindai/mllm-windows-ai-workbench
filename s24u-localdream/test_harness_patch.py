#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

MARKER = "S24U HARNESS · RAW"
APP_ID = 'applicationId = "io.github.xororz.localdream.s24uharness"'
VERSION = 'versionName = "2.8.1-s24u-h1"'
COMPILE_SDK = "compileSdk = 36"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: test_harness_patch.py <local-dream-root>", file=sys.stderr)
        return 2

    root = Path(sys.argv[1])
    gradle = (root / "app/build.gradle.kts").read_text(encoding="utf-8")
    screen = (
        root
        / "app/src/main/java/io/github/xororz/localdream/ui/screens/ModelRunScreen.kt"
    ).read_text(encoding="utf-8")
    backend = (
        root
        / "app/src/main/java/io/github/xororz/localdream/service/BackendService.kt"
    ).read_text(encoding="utf-8")

    require(APP_ID in gradle, "custom side-by-side applicationId is missing")
    require(VERSION in gradle, "S24U harness version marker is missing")
    require(COMPILE_SDK in gradle, "CI-compatible compileSdk 36 override is missing")
    require(MARKER in screen, "RAW harness UI marker is missing")
    require("RAW INPUT →" in screen, "raw prompt trace is missing")
    require("NEGATIVE →" in screen, "negative prompt trace is missing")
    require(
        'BuildConfig.FLAVOR == "filter"' in backend,
        "upstream filter flavor gate changed unexpectedly",
    )
    require(
        '"--safety_checker"' in backend,
        "safety checker wiring unexpectedly absent; upstream drift suspected",
    )
    require(
        'create("basic")' in gradle and 'create("filter")' in gradle,
        "expected basic/filter flavors missing",
    )

    print("HARNESS_PATCH_TEST_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
