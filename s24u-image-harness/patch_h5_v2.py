#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

import patch_h5


def fix_h5_runtime_contract(root: Path) -> None:
    pipeline = root / "app/src/main/cpp/src/Pipeline.hpp"
    text = pipeline.read_text(encoding="utf-8")
    if "#include <limits>" not in text:
        anchor = "#include <iostream>\n"
        if text.count(anchor) != 1:
            raise RuntimeError("H5 <limits>: include anchor not unique")
        text = text.replace(anchor, anchor + "#include <limits>\n", 1)
    pipeline.write_text(text, encoding="utf-8")

    css = root / "app/src/main/assets/s24u_microscope/microscope.css"
    text = css.read_text(encoding="utf-8")
    replacements = {
        "--primary:#4285f4;": "--primary: #4285f4;",
        "--page:#f7f7fa;": "--page: #f7f7fa;",
    }
    for old, new in replacements.items():
        if text.count(old) != 1:
            raise RuntimeError(f"H5 CSS normalization: expected one {old!r}")
        text = text.replace(old, new, 1)
    css.write_text(text, encoding="utf-8")

    js = root / "app/src/main/assets/s24u_microscope/microscope.js"
    text = js.read_text(encoding="utf-8")
    old = "window.S24UMicroscope={update(snapshot){pendingSnapshot=snapshot||{};if(!rafId)rafId=requestAnimationFrame(flush);}};"
    new = '''window.S24UMicroscope={
    update(snapshot){
      pendingSnapshot=Object.assign({},pendingSnapshot||{},snapshot||{});
      if(!rafId)rafId=requestAnimationFrame(flush);
    },
    addMedia(media){
      pendingSnapshot=Object.assign({},pendingSnapshot||{});
      if(media&&media.process_preview){
        const frame=media.process_preview;
        const frames=arr(pendingSnapshot.process_previews).slice();
        const key=int(frame.preview_index,frames.length+1);
        if(!frames.some((x)=>int(x.preview_index)===key))frames.push(frame);
        pendingSnapshot.process_previews=frames.slice(-8);
      }
      if(media&&media.latent_map){
        const frame=media.latent_map;
        const frames=arr(pendingSnapshot.latent_maps).slice();
        const key=int(frame.diffusion_step,frames.length+1);
        if(!frames.some((x)=>int(x.diffusion_step)===key))frames.push(frame);
        pendingSnapshot.latent_maps=frames.slice(-8);
      }
      if(!rafId)rafId=requestAnimationFrame(flush);
    }
  };'''
    if text.count(old) != 1:
        raise RuntimeError("H5 partial-update merge: update() anchor not unique")
    text = text.replace(old, new, 1)
    js.write_text(text, encoding="utf-8")

    screen = root / "app/src/main/java/io/github/xororz/localdream/ui/screens/ModelRunScreen.kt"
    text = screen.read_text(encoding="utf-8")
    old = '            put("h4_marker", "S24U_H4_VISUAL_MICROSCOPE")\n'
    new = '            put("h5_marker", "S24U_H5_PROCESS_MICROSCOPE")\n'
    if text.count(old) != 1:
        raise RuntimeError("H5 DEX marker: expected exactly one inherited H4 runtime marker")
    text = text.replace(old, new, 1)

    old_media = '''                        val mediaRevision = microscope.processPreviews.size * 100 + microscope.latentMaps.size
                        if (webView.tag != mediaRevision) {
                            webView.tag = mediaRevision
                            val mediaPayload = JSONObject().apply {
                                put(
                                    "process_previews",
                                    JSONArray().apply { microscope.processPreviews.forEach { put(previewJson(it)) } },
                                )
                                put(
                                    "latent_maps",
                                    JSONArray().apply { microscope.latentMaps.forEach { put(previewJson(it)) } },
                                )
                            }.toString()
                            webView.evaluateJavascript(
                                "window.S24UMicroscope && window.S24UMicroscope.update($mediaPayload);",
                                null,
                            )
                        }
'''
    new_media = '''                        val mediaRevision = microscope.processPreviews.size * 100 + microscope.latentMaps.size
                        val previousMediaRevision = webView.tag as? Int
                        if (previousMediaRevision != mediaRevision) {
                            webView.tag = mediaRevision
                            if (previousMediaRevision == null) {
                                // First WebView attach may happen after generation. Bootstrap
                                // the bounded history once so the scrubber has every saved frame.
                                val mediaPayload = JSONObject().apply {
                                    put(
                                        "process_previews",
                                        JSONArray().apply { microscope.processPreviews.forEach { put(previewJson(it)) } },
                                    )
                                    put(
                                        "latent_maps",
                                        JSONArray().apply { microscope.latentMaps.forEach { put(previewJson(it)) } },
                                    )
                                }.toString()
                                webView.evaluateJavascript(
                                    "window.S24UMicroscope && window.S24UMicroscope.update($mediaPayload);",
                                    null,
                                )
                            } else {
                                // Once attached, stream only the newest heavy frame. The JS
                                // side appends/deduplicates it into its bounded local history.
                                val mediaPayload = JSONObject().apply {
                                    microscope.processPreviews.lastOrNull()?.let {
                                        put("process_preview", previewJson(it))
                                    }
                                    microscope.latentMaps.lastOrNull()?.let {
                                        put("latent_map", previewJson(it))
                                    }
                                }.toString()
                                webView.evaluateJavascript(
                                    "window.S24UMicroscope && window.S24UMicroscope.addMedia($mediaPayload);",
                                    null,
                                )
                            }
                        }
'''
    if text.count(old_media) != 1:
        raise RuntimeError("H5 bootstrap+delta media bridge: original full-history block not unique")
    text = text.replace(old_media, new_media, 1)
    screen.write_text(text, encoding="utf-8")


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: patch_h5_v2.py <h4-patched-local-dream-root>", file=sys.stderr)
        return 2
    rc = patch_h5.main()
    if rc != 0:
        return rc
    root = Path(sys.argv[1]).resolve()
    fix_h5_runtime_contract(root)
    print("S24U_IMAGE_HARNESS_H5_V2_RUNTIME_FIXES_APPLIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
