#!/usr/bin/env python3
from __future__ import annotations

import shutil
import sys
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one literal match, found {count}")
    return text.replace(old, new, 1)


def patch_gradle(root: Path) -> None:
    p = root / "app/build.gradle.kts"
    t = p.read_text(encoding="utf-8")
    t = replace_once(t, "versionCode = 7404", "versionCode = 7405", "H5 versionCode")
    t = replace_once(t, 'versionName = "2.8.1-s24u-h4"', 'versionName = "2.8.1-s24u-h5"', "H5 versionName")
    p.write_text(t, encoding="utf-8")


def patch_pipeline(root: Path) -> None:
    p = root / "app/src/main/cpp/src/Pipeline.hpp"
    t = p.read_text(encoding="utf-8")

    t = replace_once(
        t,
        "  int hidden_dim = 0;\n};\nusing MicroscopeTraceCallback =",
        "  int hidden_dim = 0;\n  std::string image_base64;\n};\nusing MicroscopeTraceCallback =",
        "H5 trace image field",
    )

    helper = r'''
// S24U H5: cheap truthful view of the diffusion state. This does NOT claim to
// be an UNet feature map. It visualizes the four SD/SDXL latent channels after
// the scheduler step as a 2x2 normalized grayscale contact sheet. Unlike a VAE
// preview it does not invoke another model, so it is suitable for every step.
inline std::string renderLatentChannelsPreview(const xt::xarray<float> &latents) {
  try {
    if (latents.dimension() != 4 || latents.shape()[0] < 1 ||
        latents.shape()[1] < 4)
      return "";
    const int h = static_cast<int>(latents.shape()[2]);
    const int w = static_cast<int>(latents.shape()[3]);
    if (h <= 0 || w <= 0) return "";
    const int out_w = w * 2;
    const int out_h = h * 2;
    std::vector<uint8_t> rgb(static_cast<size_t>(out_w) * out_h * 3, 0);

    for (int c = 0; c < 4; ++c) {
      float lo = std::numeric_limits<float>::infinity();
      float hi = -std::numeric_limits<float>::infinity();
      for (int y = 0; y < h; ++y) {
        for (int x = 0; x < w; ++x) {
          const float v = latents(0, c, y, x);
          lo = std::min(lo, v);
          hi = std::max(hi, v);
        }
      }
      const float span = std::max(hi - lo, 1e-8f);
      const int ox = (c % 2) * w;
      const int oy = (c / 2) * h;
      for (int y = 0; y < h; ++y) {
        for (int x = 0; x < w; ++x) {
          const float normalized = (latents(0, c, y, x) - lo) / span;
          const uint8_t g = static_cast<uint8_t>(
              std::clamp(normalized * 255.0f, 0.0f, 255.0f));
          const size_t idx =
              (static_cast<size_t>(oy + y) * out_w + (ox + x)) * 3;
          rgb[idx] = g;
          rgb[idx + 1] = g;
          rgb[idx + 2] = g;
        }
      }
    }
    auto jpg = encodeJPEG(rgb, out_w, out_h, 68);
    return base64_encode(std::string(jpg.begin(), jpg.end()));
  } catch (const std::exception &e) {
    QNN_WARN("Latent channel preview failed: %s", e.what());
    return "";
  }
}

'''
    anchor = "inline GenerationResult Pipeline::generate(\n"
    t = replace_once(t, anchor, helper + anchor, "H5 latent preview helper")

    loop_anchor = '''      current_step++;
    }

    endDenoise();
'''
    loop_new = '''      MicroscopeTraceEvent latent_trace;
      latent_trace.phase = "latent_map";
      latent_trace.step = current_step;
      latent_trace.total_steps = total_run_steps;
      latent_trace.diffusion_step = i - start_step + 1;
      latent_trace.diffusion_total = static_cast<int>(timesteps.size()) - start_step;
      latent_trace.timestep = current_ts;
      latent_trace.chunk_count = static_cast<int>(conds.size());
      latent_trace.latent_width = sample_width;
      latent_trace.latent_height = sample_height;
      latent_trace.image_base64 = renderLatentChannelsPreview(latents);
      emit_trace(latent_trace);

      current_step++;
    }

    endDenoise();
'''
    t = replace_once(t, loop_anchor, loop_new, "H5 per-step latent trace")
    p.write_text(t, encoding="utf-8")


def patch_main_cpp(root: Path) -> None:
    p = root / "app/src/main/cpp/src/main.cpp"
    t = p.read_text(encoding="utf-8")
    t = replace_once(
        t,
        "              auto result = pipeline->generate(\n                  *req, [&sink, &req](int s, int t, const std::string &img) {",
        "              int preview_index = 0;\n              auto result = pipeline->generate(\n                  *req, [&sink, &req, &preview_index](int s, int t, const std::string &img) {",
        "H5 preview counter",
    )
    t = replace_once(
        t,
        '''                    if (!img.empty()) {
                      p["image"] = img;
                      p["format"] = req->preview_format;
                    }
''',
        '''                    if (!img.empty()) {
                      p["image"] = img;
                      p["format"] = req->preview_format;
                      p["preview_index"] = ++preview_index;
                    }
''',
        "H5 progress preview index",
    )
    t = replace_once(
        t,
        '''                        {"seq_len", trace.seq_len},
                        {"hidden_dim", trace.hidden_dim}};
''',
        '''                        {"seq_len", trace.seq_len},
                        {"hidden_dim", trace.hidden_dim},
                        {"image_base64", trace.image_base64}};
''',
        "H5 trace image serialization",
    )
    p.write_text(t, encoding="utf-8")


def patch_service(root: Path) -> None:
    p = root / "app/src/main/java/io/github/xororz/localdream/service/BackgroundGenerationService.kt"
    t = p.read_text(encoding="utf-8")

    t = replace_once(
        t,
        "    data class MicroscopeEvent(\n",
        '''    data class MicroscopePreview(
        val kind: String,
        val step: Int = 0,
        val totalSteps: Int = 0,
        val previewIndex: Int = 0,
        val diffusionStep: Int = 0,
        val diffusionTotal: Int = 0,
        val timestep: Float = 0f,
        val latentWidth: Int = 0,
        val latentHeight: Int = 0,
        val format: String = "jpeg",
        val imageBase64: String,
    )

    data class MicroscopeEvent(
''',
        "H5 preview data class",
    )
    t = replace_once(
        t,
        '''        val maxChunks: Int = 8,
    )

    data class MicroscopeSnapshot(
''',
        '''        val maxChunks: Int = 8,
        val imageBase64: String = "",
    )

    data class MicroscopeSnapshot(
''',
        "H5 event image field",
    )
    t = replace_once(
        t,
        '''        val maxChunks: Int = 8,
    )

    sealed class GenerationState {
''',
        '''        val maxChunks: Int = 8,
        val processPreviews: List<MicroscopePreview> = emptyList(),
        val latentMaps: List<MicroscopePreview> = emptyList(),
    )

    sealed class GenerationState {
''',
        "H5 snapshot media lists",
    )
    t = replace_once(
        t,
        '''            maxChunks = message.optInt("max_chunks", 8).coerceAtLeast(1),
        )
''',
        '''            maxChunks = message.optInt("max_chunks", 8).coerceAtLeast(1),
            imageBase64 = message.optString("image_base64", ""),
        )
''',
        "H5 trace image parser",
    )
    t = replace_once(
        t,
        '''        _microscopeState.value = next
    }
''',
        '''        if (event.phase == "latent_map" && event.imageBase64.isNotBlank()) {
            val latentPreview = MicroscopePreview(
                kind = "latent4",
                step = event.step,
                totalSteps = event.totalSteps,
                diffusionStep = event.diffusionStep,
                diffusionTotal = event.diffusionTotal,
                timestep = event.timestep,
                latentWidth = event.latentWidth,
                latentHeight = event.latentHeight,
                format = "jpeg",
                imageBase64 = event.imageBase64,
            )
            next = next.copy(latentMaps = (previous.latentMaps + latentPreview).takeLast(8))
        }
        _microscopeState.value = next
    }
''',
        "H5 latent map reducer",
    )

    t = replace_once(
        t,
        '''            val showProcess = preferences.getBoolean("show_diffusion_process", false)
            val showStride = preferences.getInt("show_diffusion_stride", 1)
''',
        '''            val configuredStride = preferences.getInt("show_diffusion_stride", 1).coerceAtLeast(1)
            // Microscope harness: preserve at most ~8 truthful VAE process frames.
            // DMD2 6-8 step runs therefore keep every step; long schedules are
            // sampled so observability does not multiply VAE decode cost without bound.
            val microscopePreviewStride = maxOf(configuredStride, maxOf(1, (steps + 7) / 8))
''',
        "H5 bounded preview stride",
    )
    t = replace_once(
        t,
        '''                put("show_diffusion_process", if (ultrafix) false else showProcess)
                put("show_diffusion_stride", showStride)
''',
        '''                put("show_diffusion_process", if (ultrafix) false else true)
                put("show_diffusion_stride", microscopePreviewStride)
''',
        "H5 force real process preview",
    )
    t = replace_once(
        t,
        '''                                    val b64Img = message.optString("image")
                                    var bitmap: Bitmap? = null
                                    if (b64Img.isNotEmpty()) {
''',
        '''                                    val b64Img = message.optString("image")
                                    val previewIndex = message.optInt("preview_index", 0)
                                    if (b64Img.isNotEmpty()) {
                                        val previousMicroscope = _microscopeState.value
                                        val preview = MicroscopePreview(
                                            kind = "vae",
                                            step = step,
                                            totalSteps = totalSteps,
                                            previewIndex = previewIndex,
                                            format = message.optString("format", "jpeg"),
                                            imageBase64 = b64Img,
                                        )
                                        _microscopeState.value = previousMicroscope.copy(
                                            processPreviews = (previousMicroscope.processPreviews.takeLast(7) + preview),
                                        )
                                    }
                                    var bitmap: Bitmap? = null
                                    if (b64Img.isNotEmpty()) {
''',
        "H5 process preview history",
    )
    p.write_text(t, encoding="utf-8")


def patch_screen(root: Path) -> None:
    p = root / "app/src/main/java/io/github/xororz/localdream/ui/screens/ModelRunScreen.kt"
    t = p.read_text(encoding="utf-8")
    t = replace_once(t, "// S24U_H4_VISUAL_MICROSCOPE", "// S24U_H5_PROCESS_MICROSCOPE", "H5 runtime marker")

    helper_anchor = '''        fun eventJson(event: BackgroundGenerationService.MicroscopeEvent): JSONObject = JSONObject().apply {
'''
    helper = '''        fun previewJson(preview: BackgroundGenerationService.MicroscopePreview): JSONObject = JSONObject().apply {
            put("kind", preview.kind)
            put("step", preview.step)
            put("total_steps", preview.totalSteps)
            put("preview_index", preview.previewIndex)
            put("diffusion_step", preview.diffusionStep)
            put("diffusion_total", preview.diffusionTotal)
            put("timestep", preview.timestep.toDouble())
            put("latent_width", preview.latentWidth)
            put("latent_height", preview.latentHeight)
            put("format", preview.format)
            put("image_base64", preview.imageBase64)
        }

'''
    t = replace_once(t, helper_anchor, helper + helper_anchor, "H5 preview JSON helper")
    t = replace_once(
        t,
        '''            put("events", JSONArray().apply { microscope.events.forEach { put(eventJson(it)) } })
''',
        '''            put("events", JSONArray().apply { microscope.events.takeLast(48).forEach { put(eventJson(it)) } })
''',
        "H5 event bridge cap",
    )

    old_update = '''                update = { webView ->
                    if (pageReady) {
                        webView.evaluateJavascript(
                            "window.S24UMicroscope && window.S24UMicroscope.update($payload);",
                            null,
                        )
                    }
                },
'''
    new_update = '''                update = { webView ->
                    if (pageReady) {
                        // Telemetry is light and may change every trace event. Media is
                        // sent only when a new process/latent frame appears, avoiding
                        // repeated multi-hundred-KB evaluateJavascript payloads.
                        webView.evaluateJavascript(
                            "window.S24UMicroscope && window.S24UMicroscope.update($payload);",
                            null,
                        )
                        val mediaRevision = microscope.processPreviews.size * 100 + microscope.latentMaps.size
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
                    }
                },
'''
    t = replace_once(t, old_update, new_update, "H5 split media bridge")
    p.write_text(t, encoding="utf-8")


def copy_assets(root: Path) -> None:
    src = Path(__file__).resolve().parent / "h5_assets" / "microscope"
    dst = root / "app/src/main/assets/s24u_microscope"
    for name in ("index.html", "microscope.css", "microscope.js"):
        if not (src / name).is_file():
            raise RuntimeError(f"H5 microscope asset missing: {name}")
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: patch_h5.py <h4-patched-local-dream-root>", file=sys.stderr)
        return 2
    root = Path(sys.argv[1]).resolve()
    patch_gradle(root)
    patch_pipeline(root)
    patch_main_cpp(root)
    patch_service(root)
    patch_screen(root)
    copy_assets(root)
    print("S24U_IMAGE_HARNESS_H5_PROCESS_MICROSCOPE_PATCH_APPLIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
