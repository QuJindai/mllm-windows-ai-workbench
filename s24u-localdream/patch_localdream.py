#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: patch_localdream.py <local-dream-root>", file=sys.stderr)
        return 2

    root = Path(sys.argv[1])

    gradle_path = root / "app/build.gradle.kts"
    gradle = gradle_path.read_text(encoding="utf-8")
    gradle = replace_once(
        gradle,
        'applicationId = "io.github.xororz.localdream"',
        'applicationId = "io.github.xororz.localdream.s24uharness"',
        "applicationId",
    )
    gradle = replace_once(gradle, "compileSdk = 37", "compileSdk = 36", "compileSdk")
    gradle = replace_once(gradle, "versionCode = 74", "versionCode = 7401", "versionCode")
    gradle = replace_once(
        gradle,
        'versionName = "2.8.1"',
        'versionName = "2.8.1-s24u-h1"',
        "versionName",
    )
    gradle_path.write_text(gradle, encoding="utf-8")

    strings_path = root / "app/src/main/res/values/strings.xml"
    strings = strings_path.read_text(encoding="utf-8")
    strings, n = re.subn(
        r'(<string\s+name="app_name"[^>]*>)(.*?)(</string>)',
        r'\1S24U Image Harness\3',
        strings,
        count=1,
        flags=re.DOTALL,
    )
    if n != 1:
        raise RuntimeError("app_name: expected exactly one string resource")
    strings_path.write_text(strings, encoding="utf-8")

    screen_path = root / "app/src/main/java/io/github/xororz/localdream/ui/screens/ModelRunScreen.kt"
    screen = screen_path.read_text(encoding="utf-8")
    anchor = """                        ControlledPromptTagTextField(\n                            controller = promptField,\n"""
    harness_card = """                        Card(\n                            modifier = Modifier.fillMaxWidth(),\n                            colors = CardDefaults.cardColors(\n                                containerColor = MaterialTheme.colorScheme.surfaceVariant,\n                            ),\n                        ) {\n                            Column(\n                                modifier = Modifier.padding(12.dp),\n                                verticalArrangement = Arrangement.spacedBy(4.dp),\n                            ) {\n                                Text(\n                                    text = \"S24U HARNESS · RAW\",\n                                    style = MaterialTheme.typography.titleSmall,\n                                    fontWeight = FontWeight.Bold,\n                                )\n                                Text(\n                                    text = \"No LLM semantic rewrite. Basic build: optional Safety Checker is not loaded.\",\n                                    style = MaterialTheme.typography.bodySmall,\n                                )\n                                Text(\n                                    text = \"RAW INPUT → ${promptField.text.ifBlank { \"(empty)\" }}\",\n                                    style = MaterialTheme.typography.bodySmall,\n                                )\n                                Text(\n                                    text = \"NEGATIVE → ${negativePromptField.text.ifBlank { \"(empty)\" }}\",\n                                    style = MaterialTheme.typography.bodySmall,\n                                )\n                                Text(\n                                    text = \"TOKENS → ${promptField.tokenCount}/${promptField.tokenMax}\",\n                                    style = MaterialTheme.typography.labelSmall,\n                                )\n                            }\n                        }\n\n"""
    screen = replace_once(screen, anchor, harness_card + anchor, "prompt field anchor")
    screen_path.write_text(screen, encoding="utf-8")

    print("S24U_LOCALDREAM_PATCH_APPLIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
