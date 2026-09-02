#!/usr/bin/env python3
from __future__ import annotations

import inspect

import patch_h6_v11_token_truth as base


_original_replace_once = base.replace_once


def stable_replace_once(text: str, old: str, new: str, label: str) -> str:
    if label == "single conditioning CLIP execution facts":
        needle = "  encodeText(processed, !neg_hit, !pos_hit, cond);\n"
        replacement = (
            needle
            + "  cond.negative_clip_executed = !neg_hit;\n"
            + "  cond.positive_clip_executed = !pos_hit;\n"
        )
        return _original_replace_once(text, needle, replacement, label)
    if label == "event guidance fact fields":
        count = text.count(old)
        if count != 2:
            raise RuntimeError(
                f"{label}: expected shared Event/Snapshot anchor twice, found {count}"
            )
        return text.replace(old, new, 1)
    if label == "event token preservation parser":
        needle = '            maxChunks = message.optInt("max_chunks", 8).coerceAtLeast(1),\n'
        replacement = (
            needle
            + '            positiveChunkTokenIds = jsonNestedIntList(message, "positive_chunk_token_ids"),\n'
            + '            negativeChunkTokenIds = jsonNestedIntList(message, "negative_chunk_token_ids"),\n'
            + '            positiveTokenPreserved = message.optBoolean("positive_token_preserved", true),\n'
            + '            negativeTokenPreserved = message.optBoolean("negative_token_preserved", true),\n'
        )
        return _original_replace_once(text, needle, replacement, label)
    return _original_replace_once(text, old, new, label)


def install_stable_service_patch() -> None:
    source = inspect.getsource(base.patch_service)
    start = source.index("    # Add matching event fields next to maxChunks")
    end = source.index("\n\n    json_helper_anchor", start)
    replacement = '''    # H6R4 Event already carries H5/H6 media/influence fields after maxChunks,
    # so anchor within the Event body instead of assuming maxChunks ends the class.
    event_anchor = (
        "        val maxChunks: Int = 8,\\n"
        "        val imageBase64: String = \\\"\\\",\\n"
    )
    event_new = (
        "        val maxChunks: Int = 8,\\n"
        "        val positiveChunkTokenIds: List<List<Int>> = emptyList(),\\n"
        "        val negativeChunkTokenIds: List<List<Int>> = emptyList(),\\n"
        "        val positiveTokenPreserved: Boolean = true,\\n"
        "        val negativeTokenPreserved: Boolean = true,\\n"
        "        val imageBase64: String = \\\"\\\",\\n"
    )
    text = replace_once(
        text, event_anchor, event_new, "event token preservation fields"
    )'''
    source = source[:start] + replacement + source[end:]
    namespace = base.__dict__
    exec(source, namespace)
    base.patch_service = namespace["patch_service"]


def install_stable_js_patch() -> None:
    source = inspect.getsource(base.patch_js)
    source = source.replace(
        '    needle = "  function renderBudget(s){"',
        '    needle = "  function renderBudget(s) {"',
        1,
    )
    namespace = base.__dict__
    exec(source, namespace)
    base.patch_js = namespace["patch_js"]


def main() -> int:
    base.replace_once = stable_replace_once
    install_stable_service_patch()
    install_stable_js_patch()
    rc = base.main()
    if rc == 0:
        print("S24U_IMAGE_HARNESS_H6R4_TOKEN_TRUTH_V2_APPLIED")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
