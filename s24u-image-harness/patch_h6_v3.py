#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one literal match, found {count}")
    return text.replace(old, new, 1)


def regex_once(text: str, pattern: str, replacement: str, label: str) -> str:
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.DOTALL)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one regex match, found {count}")
    return updated


def patch_screen(root: Path) -> None:
    path = root / "app/src/main/java/io/github/xororz/localdream/ui/screens/ModelRunScreen.kt"
    text = path.read_text(encoding="utf-8")

    old = '''                        val mediaRevision = listOf(
                            microscope.processPreviews.lastOrNull()?.previewIndex ?: 0,
                            microscope.latentMaps.lastOrNull()?.diffusionStep ?: 0,
                            microscope.influenceSamples.lastOrNull()?.let {
                                it.diffusionStep * 100 + it.chunkIndex + 1
                            } ?: 0,
                        )
                        val previousMediaRevision = webView.tag as? List<*>
                        if (previousMediaRevision != mediaRevision) {
                            webView.tag = mediaRevision
                            val mediaReset = microscope.processPreviews.isEmpty() &&
                                microscope.latentMaps.isEmpty() && microscope.influenceSamples.isEmpty()
                            if (previousMediaRevision == null || mediaReset) {
                                // First attach (or a new generation reset) bootstraps bounded
                                // history exactly once. Raw prediction tensors never cross JNI.
                                val mediaPayload = JSONObject().apply {
                                    put(
                                        "process_previews",
                                        JSONArray().apply { microscope.processPreviews.forEach { put(previewJson(it)) } },
                                    )
                                    put(
                                        "latent_maps",
                                        JSONArray().apply { microscope.latentMaps.forEach { put(previewJson(it)) } },
                                    )
                                    put("influence_samples", JSONArray().apply {
                                        microscope.influenceSamples.forEach { put(influenceJson(it)) }
                                    })
                                }.toString()
                                webView.evaluateJavascript(
                                    "window.S24UMicroscope && window.S24UMicroscope.update($mediaPayload);",
                                    null,
                                )
                            } else {
                                // Stream only media whose revision changed. Influence changes
                                // therefore do not resend the latest VAE/latent JPEGs.
                                val mediaPayload = JSONObject().apply {
                                    if (previousMediaRevision.getOrNull(0) != mediaRevision[0]) {
                                        microscope.processPreviews.lastOrNull()?.let {
                                            put("process_preview", previewJson(it))
                                        }
                                    }
                                    if (previousMediaRevision.getOrNull(1) != mediaRevision[1]) {
                                        microscope.latentMaps.lastOrNull()?.let {
                                            put("latent_map", previewJson(it))
                                        }
                                    }
                                    if (previousMediaRevision.getOrNull(2) != mediaRevision[2]) {
                                        microscope.influenceSamples.lastOrNull()?.let {
                                            put("influence_sample", influenceJson(it))
                                        }
                                    }
                                }.toString()
                                webView.evaluateJavascript(
                                    "window.S24UMicroscope && window.S24UMicroscope.addMedia($mediaPayload);",
                                    null,
                                )
                            }
                        }
'''

    new = '''                        val currentInfluenceRevision =
                            microscope.influenceSamples.lastOrNull()?.let {
                                it.diffusionStep * 100 + it.chunkIndex + 1
                            } ?: 0
                        val mediaRevision = listOf(
                            microscope.processPreviews.lastOrNull()?.previewIndex ?: 0,
                            microscope.latentMaps.lastOrNull()?.diffusionStep ?: 0,
                            currentInfluenceRevision,
                        )
                        val previousMediaRevision = webView.tag as? List<*>
                        val previousInfluenceRevision =
                            (previousMediaRevision?.getOrNull(2) as? Int) ?: 0
                        if (previousMediaRevision != mediaRevision) {
                            val mediaReset = microscope.processPreviews.isEmpty() &&
                                microscope.latentMaps.isEmpty() && microscope.influenceSamples.isEmpty()
                            val mediaRolledBack = previousMediaRevision != null &&
                                mediaRevision.indices.any { index ->
                                    val previous = previousMediaRevision.getOrNull(index) as? Int ?: 0
                                    mediaRevision[index] > 0 && previous > mediaRevision[index]
                                }
                            webView.tag = mediaRevision
                            if (previousMediaRevision == null || mediaReset || mediaRolledBack) {
                                // First attach, explicit reset, or a revision rollback means the
                                // WebView cannot safely infer which samples it missed. Bootstrap
                                // the bounded truth once and restart delta tracking from here.
                                val mediaPayload = JSONObject().apply {
                                    put(
                                        "process_previews",
                                        JSONArray().apply { microscope.processPreviews.forEach { put(previewJson(it)) } },
                                    )
                                    put(
                                        "latent_maps",
                                        JSONArray().apply { microscope.latentMaps.forEach { put(previewJson(it)) } },
                                    )
                                    put("influence_samples", JSONArray().apply {
                                        microscope.influenceSamples.forEach { put(influenceJson(it)) }
                                    })
                                }.toString()
                                webView.evaluateJavascript(
                                    "window.S24UMicroscope && window.S24UMicroscope.update($mediaPayload);",
                                    null,
                                )
                            } else {
                                // StateFlow/Compose may conflate several native influence events.
                                // Replay every retained sample newer than the last WebView
                                // revision instead of forwarding only lastOrNull().
                                val influenceDelta = microscope.influenceSamples.filter {
                                    it.diffusionStep * 100 + it.chunkIndex + 1 > previousInfluenceRevision
                                }
                                val mediaPayload = JSONObject().apply {
                                    if (previousMediaRevision.getOrNull(0) != mediaRevision[0]) {
                                        microscope.processPreviews.lastOrNull()?.let {
                                            put("process_preview", previewJson(it))
                                        }
                                    }
                                    if (previousMediaRevision.getOrNull(1) != mediaRevision[1]) {
                                        microscope.latentMaps.lastOrNull()?.let {
                                            put("latent_map", previewJson(it))
                                        }
                                    }
                                    if (influenceDelta.isNotEmpty()) {
                                        put("influence_samples_delta", JSONArray().apply {
                                            influenceDelta.forEach { put(influenceJson(it)) }
                                        })
                                    }
                                }.toString()
                                webView.evaluateJavascript(
                                    "window.S24UMicroscope && window.S24UMicroscope.addMedia($mediaPayload);",
                                    null,
                                )
                            }
                        }
'''

    text = replace_once(text, old, new, "H6 V3 drop-free influence bridge")
    path.write_text(text, encoding="utf-8")


def patch_js(root: Path) -> None:
    path = root / "app/src/main/assets/s24u_microscope/microscope.js"
    text = path.read_text(encoding="utf-8")

    pattern = r'''      if\(media&&media\.influence_sample\)\{\n.*?\n      \}\n      if\(!rafId\)rafId=requestAnimationFrame\(flush\);'''
    replacement = '''      if(media&&media.influence_samples_delta){
        const influence_samples_delta=arr(media.influence_samples_delta);
        const samples=arr(pendingSnapshot.influence_samples).slice();
        influence_samples_delta.forEach((sample)=>{
          const key=`${int(sample.diffusion_step)}:${int(sample.chunk_index)}`;
          const idx=samples.findIndex(x=>`${int(x.diffusion_step)}:${int(x.chunk_index)}`===key);
          if(idx>=0)samples[idx]=sample;else samples.push(sample);
        });
        pendingSnapshot.influence_samples=samples.slice(-32);
      }
      if(!rafId)rafId=requestAnimationFrame(flush);'''

    text = regex_once(text, pattern, replacement, "H6 V3 batched influence JS replay")
    path.write_text(text, encoding="utf-8")


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: patch_h6_v3.py <h6-v2-patched-local-dream-root>", file=sys.stderr)
        return 2

    root = Path(sys.argv[1]).resolve()
    patch_screen(root)
    patch_js(root)
    print("S24U_IMAGE_HARNESS_H6_V3_DROP_FREE_INFLUENCE_BRIDGE_APPLIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
