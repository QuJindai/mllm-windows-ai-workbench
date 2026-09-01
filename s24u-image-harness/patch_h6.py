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
    path = root / "app/build.gradle.kts"
    text = path.read_text(encoding="utf-8")
    text = replace_once(text, "versionCode = 7405", "versionCode = 7406", "H6 versionCode")
    text = replace_once(
        text,
        'versionName = "2.8.1-s24u-h5"',
        'versionName = "2.8.1-s24u-h6"',
        "H6 versionName",
    )
    path.write_text(text, encoding="utf-8")


def patch_pipeline(root: Path) -> None:
    path = root / "app/src/main/cpp/src/Pipeline.hpp"
    text = path.read_text(encoding="utf-8")

    text = replace_once(
        text,
        "  int hidden_dim = 0;\n  std::string image_base64;\n};\nusing MicroscopeTraceCallback =",
        "  int hidden_dim = 0;\n"
        "  std::string image_base64;\n"
        "  int influence_chunk_index = -1;\n"
        "  int influence_chunk_count = 0;\n"
        "  float influence_mean_abs = 0.0f;\n"
        "  float influence_l2 = 0.0f;\n"
        "  float influence_fused_cosine = 0.0f;\n"
        "  float influence_delta_l2 = 0.0f;\n"
        "};\nusing MicroscopeTraceCallback =",
        "H6 trace influence fields",
    )

    helpers = r'''
// S24U H6 conditioning influence metrics. These functions observe the exact
// per-chunk CFG prediction and the arithmetic-mean fused prediction that H2
// already sends to the scheduler. They do not run CLIP/UNet/VAE again.
inline void computeConditioningInfluenceMetrics(
    const xt::xarray<float> &chunk_pred, const xt::xarray<float> &fused_pred,
    float &mean_abs, float &l2, float &fused_cosine, float &delta_l2) {
  mean_abs = 0.0f;
  l2 = 0.0f;
  fused_cosine = 0.0f;
  delta_l2 = 0.0f;
  if (chunk_pred.size() == 0 || chunk_pred.size() != fused_pred.size()) return;

  double sum_abs = 0.0;
  double chunk_sq = 0.0;
  double fused_sq = 0.0;
  double dot = 0.0;
  double delta_sq = 0.0;
  auto chunk_it = chunk_pred.cbegin();
  auto fused_it = fused_pred.cbegin();
  for (; chunk_it != chunk_pred.cend(); ++chunk_it, ++fused_it) {
    const double c = static_cast<double>(*chunk_it);
    const double f = static_cast<double>(*fused_it);
    const double d = c - f;
    sum_abs += std::fabs(c);
    chunk_sq += c * c;
    fused_sq += f * f;
    dot += c * f;
    delta_sq += d * d;
  }
  mean_abs = static_cast<float>(sum_abs / static_cast<double>(chunk_pred.size()));
  l2 = static_cast<float>(std::sqrt(chunk_sq));
  delta_l2 = static_cast<float>(std::sqrt(delta_sq));
  const double denom = std::sqrt(chunk_sq) * std::sqrt(fused_sq);
  fused_cosine = denom > 1e-12 ? static_cast<float>(dot / denom) : 0.0f;
}

// Spatial influence preview: mean over latent channels of the real absolute
// difference |chunk_pred - fused_pred|. Min/max normalization is visualization
// only; scalar metrics above always use the original float tensors.
inline std::string renderConditioningInfluencePreview(
    const xt::xarray<float> &chunk_pred, const xt::xarray<float> &fused_pred) {
  try {
    if (chunk_pred.dimension() != 4 || fused_pred.dimension() != 4 ||
        chunk_pred.shape() != fused_pred.shape() || chunk_pred.shape()[0] < 1 ||
        chunk_pred.shape()[1] < 1)
      return "";
    xt::xarray<float> delta = xt::eval(xt::abs(chunk_pred - fused_pred));
    const int channels = static_cast<int>(delta.shape()[1]);
    const int h = static_cast<int>(delta.shape()[2]);
    const int w = static_cast<int>(delta.shape()[3]);
    if (channels <= 0 || h <= 0 || w <= 0) return "";

    std::vector<float> plane(static_cast<size_t>(w) * h, 0.0f);
    float lo = std::numeric_limits<float>::infinity();
    float hi = -std::numeric_limits<float>::infinity();
    for (int y = 0; y < h; ++y) {
      for (int x = 0; x < w; ++x) {
        float value = 0.0f;
        for (int c = 0; c < channels; ++c) value += delta(0, c, y, x);
        value /= static_cast<float>(channels);
        plane[static_cast<size_t>(y) * w + x] = value;
        lo = std::min(lo, value);
        hi = std::max(hi, value);
      }
    }

    const float span = std::max(hi - lo, 1e-12f);
    std::vector<uint8_t> rgb(static_cast<size_t>(w) * h * 3, 0);
    for (int y = 0; y < h; ++y) {
      for (int x = 0; x < w; ++x) {
        const float normalized =
            (plane[static_cast<size_t>(y) * w + x] - lo) / span;
        const uint8_t g = static_cast<uint8_t>(
            std::clamp(normalized * 255.0f, 0.0f, 255.0f));
        const size_t idx = (static_cast<size_t>(y) * w + x) * 3;
        rgb[idx] = g;
        rgb[idx + 1] = g;
        rgb[idx + 2] = g;
      }
    }
    auto jpg = encodeJPEG(rgb, w, h, 62);
    return base64_encode(std::string(jpg.begin(), jpg.end()));
  } catch (const std::exception &e) {
    QNN_WARN("Conditioning influence preview failed: %s", e.what());
    return "";
  }
}

'''
    generate_anchor = "inline GenerationResult Pipeline::generate(\n"
    text = replace_once(
        text,
        generate_anchor,
        helpers + generate_anchor,
        "H6 influence helper insertion",
    )

    text = replace_once(
        text,
        "      xt::xarray<float> noise_pred = xt::zeros<float>(shape);\n"
        "      for (auto &chunk_cond : conds) {\n",
        "      std::vector<xt::xarray<float>> chunk_predictions;\n"
        "      chunk_predictions.reserve(conds.size());\n"
        "      xt::xarray<float> noise_pred = xt::zeros<float>(shape);\n"
        "      for (auto &chunk_cond : conds) {\n",
        "H6 bounded current-step chunk capture",
    )
    text = replace_once(
        text,
        "        noise_pred = xt::eval(noise_pred + chunk_pred);\n"
        "      }\n"
        "      noise_pred = xt::eval(noise_pred / (float)conds.size());\n",
        "        chunk_predictions.push_back(chunk_pred);\n"
        "        noise_pred = xt::eval(noise_pred + chunk_pred);\n"
        "      }\n"
        "      noise_pred = xt::eval(noise_pred / (float)conds.size());\n",
        "H6 preserve H2 fusion plus capture",
    )

    scheduler_anchor = "      auto scheduler_start = std::chrono::high_resolution_clock::now();\n"
    influence_emit = r'''      for (size_t chunk_index = 0; chunk_index < chunk_predictions.size();
           ++chunk_index) {
        float influence_mean_abs = 0.0f;
        float influence_l2 = 0.0f;
        float influence_fused_cosine = 0.0f;
        float influence_delta_l2 = 0.0f;
        computeConditioningInfluenceMetrics(
            chunk_predictions[chunk_index], noise_pred, influence_mean_abs,
            influence_l2, influence_fused_cosine, influence_delta_l2);

        MicroscopeTraceEvent influence_trace;
        influence_trace.phase = "conditioning_influence";
        influence_trace.step = current_step;
        influence_trace.total_steps = total_run_steps;
        influence_trace.diffusion_step = i - start_step + 1;
        influence_trace.diffusion_total =
            static_cast<int>(timesteps.size()) - start_step;
        influence_trace.timestep = current_ts;
        influence_trace.chunk_count = static_cast<int>(conds.size());
        influence_trace.latent_width = sample_width;
        influence_trace.latent_height = sample_height;
        influence_trace.seq_len = cond.seq_len;
        influence_trace.hidden_dim = cond.hidden_dim;
        influence_trace.influence_chunk_index = static_cast<int>(chunk_index);
        influence_trace.influence_chunk_count =
            static_cast<int>(chunk_predictions.size());
        influence_trace.influence_mean_abs = influence_mean_abs;
        influence_trace.influence_l2 = influence_l2;
        influence_trace.influence_fused_cosine = influence_fused_cosine;
        influence_trace.influence_delta_l2 = influence_delta_l2;
        influence_trace.image_base64 = renderConditioningInfluencePreview(
            chunk_predictions[chunk_index], noise_pred);
        emit_trace(influence_trace);
      }

'''
    text = replace_once(
        text,
        scheduler_anchor,
        influence_emit + scheduler_anchor,
        "H6 emit influence before scheduler",
    )
    path.write_text(text, encoding="utf-8")


def patch_main_cpp(root: Path) -> None:
    path = root / "app/src/main/cpp/src/main.cpp"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '''                        {"seq_len", trace.seq_len},
                        {"hidden_dim", trace.hidden_dim},
                        {"image_base64", trace.image_base64}};
''',
        '''                        {"seq_len", trace.seq_len},
                        {"hidden_dim", trace.hidden_dim},
                        {"influence_chunk_index", trace.influence_chunk_index},
                        {"influence_chunk_count", trace.influence_chunk_count},
                        {"influence_mean_abs", trace.influence_mean_abs},
                        {"influence_l2", trace.influence_l2},
                        {"influence_fused_cosine", trace.influence_fused_cosine},
                        {"influence_delta_l2", trace.influence_delta_l2},
                        {"image_base64", trace.image_base64}};
''',
        "H6 native SSE influence serialization",
    )
    path.write_text(text, encoding="utf-8")


def patch_service(root: Path) -> None:
    path = root / "app/src/main/java/io/github/xororz/localdream/service/BackgroundGenerationService.kt"
    text = path.read_text(encoding="utf-8")

    text = replace_once(
        text,
        "    data class MicroscopeEvent(\n",
        '''    data class InfluenceSample(
        val diffusionStep: Int = 0,
        val diffusionTotal: Int = 0,
        val timestep: Float = 0f,
        val chunkIndex: Int = 0,
        val chunkCount: Int = 1,
        val meanAbs: Float = 0f,
        val l2: Float = 0f,
        val fusedCosine: Float = 0f,
        val deltaL2: Float = 0f,
        val imageBase64: String = "",
    )

    data class MicroscopeEvent(
''',
        "H6 influence sample model",
    )
    text = replace_once(
        text,
        '''        val maxChunks: Int = 8,
        val imageBase64: String = "",
    )

    data class MicroscopeSnapshot(
''',
        '''        val maxChunks: Int = 8,
        val imageBase64: String = "",
        val influenceChunkIndex: Int = -1,
        val influenceChunkCount: Int = 0,
        val influenceMeanAbs: Float = 0f,
        val influenceL2: Float = 0f,
        val influenceFusedCosine: Float = 0f,
        val influenceDeltaL2: Float = 0f,
    )

    data class MicroscopeSnapshot(
''',
        "H6 microscope event influence fields",
    )
    text = replace_once(
        text,
        '''        val processPreviews: List<MicroscopePreview> = emptyList(),
        val latentMaps: List<MicroscopePreview> = emptyList(),
    )

    sealed class GenerationState {
''',
        '''        val processPreviews: List<MicroscopePreview> = emptyList(),
        val latentMaps: List<MicroscopePreview> = emptyList(),
        val influenceSamples: List<InfluenceSample> = emptyList(),
    )

    sealed class GenerationState {
''',
        "H6 bounded influence history",
    )
    text = replace_once(
        text,
        '''            maxChunks = message.optInt("max_chunks", 8).coerceAtLeast(1),
            imageBase64 = message.optString("image_base64", ""),
        )
''',
        '''            maxChunks = message.optInt("max_chunks", 8).coerceAtLeast(1),
            imageBase64 = message.optString("image_base64", ""),
            influenceChunkIndex = message.optInt("influence_chunk_index", -1),
            influenceChunkCount = message.optInt("influence_chunk_count", 0),
            influenceMeanAbs = message.optDouble("influence_mean_abs", 0.0).toFloat(),
            influenceL2 = message.optDouble("influence_l2", 0.0).toFloat(),
            influenceFusedCosine = message.optDouble("influence_fused_cosine", 0.0).toFloat(),
            influenceDeltaL2 = message.optDouble("influence_delta_l2", 0.0).toFloat(),
        )
''',
        "H6 influence trace parser",
    )
    text = replace_once(
        text,
        '''        _microscopeState.value = next
    }
''',
        '''        if (event.phase == "conditioning_influence" && event.influenceChunkIndex >= 0) {
            val influenceSample = InfluenceSample(
                diffusionStep = event.diffusionStep,
                diffusionTotal = event.diffusionTotal,
                timestep = event.timestep,
                chunkIndex = event.influenceChunkIndex,
                chunkCount = event.influenceChunkCount.coerceAtLeast(1),
                meanAbs = event.influenceMeanAbs,
                l2 = event.influenceL2,
                fusedCosine = event.influenceFusedCosine,
                deltaL2 = event.influenceDeltaL2,
                imageBase64 = event.imageBase64,
            )
            next = next.copy(
                influenceSamples = (next.influenceSamples + influenceSample).takeLast(32),
            )
        }
        _microscopeState.value = next
    }
''',
        "H6 influence reducer",
    )
    path.write_text(text, encoding="utf-8")


def patch_screen(root: Path) -> None:
    path = root / "app/src/main/java/io/github/xororz/localdream/ui/screens/ModelRunScreen.kt"
    text = path.read_text(encoding="utf-8")

    text = replace_once(
        text,
        "// S24U_H5_PROCESS_MICROSCOPE",
        "// S24U_H6_CONDITIONING_INFLUENCE",
        "H6 source runtime marker",
    )
    text = replace_once(
        text,
        '            put("h5_marker", "S24U_H5_PROCESS_MICROSCOPE")\n',
        '            put("h6_marker", "S24U_H6_CONDITIONING_INFLUENCE")\n',
        "H6 compiled DEX marker",
    )

    event_anchor = '''        fun eventJson(event: BackgroundGenerationService.MicroscopeEvent): JSONObject = JSONObject().apply {
'''
    influence_helper = '''        fun influenceJson(sample: BackgroundGenerationService.InfluenceSample): JSONObject = JSONObject().apply {
            put("diffusion_step", sample.diffusionStep)
            put("diffusion_total", sample.diffusionTotal)
            put("timestep", sample.timestep.toDouble())
            put("chunk_index", sample.chunkIndex)
            put("chunk_count", sample.chunkCount)
            put("mean_abs", sample.meanAbs.toDouble())
            put("l2", sample.l2.toDouble())
            put("fused_cosine", sample.fusedCosine.toDouble())
            put("delta_l2", sample.deltaL2.toDouble())
            put("image_base64", sample.imageBase64)
        }

'''
    text = replace_once(
        text,
        event_anchor,
        influence_helper + event_anchor,
        "H6 influence JSON helper",
    )

    old_media = '''                        val mediaRevision = microscope.processPreviews.size * 100 + microscope.latentMaps.size
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
    new_media = '''                        val mediaRevision = listOf(
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
    text = replace_once(
        text,
        old_media,
        new_media,
        "H6 bootstrap+delta influence bridge",
    )
    path.write_text(text, encoding="utf-8")


def copy_assets(root: Path) -> None:
    src = Path(__file__).resolve().parent / "h6_assets" / "microscope"
    dst = root / "app/src/main/assets/s24u_microscope"
    for name in ("index.html", "microscope.css", "microscope.js"):
        if not (src / name).is_file():
            raise RuntimeError(f"H6 microscope asset missing: {name}")
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: patch_h6.py <h5-patched-local-dream-root>", file=sys.stderr)
        return 2
    root = Path(sys.argv[1]).resolve()
    patch_gradle(root)
    patch_pipeline(root)
    patch_main_cpp(root)
    patch_service(root)
    patch_screen(root)
    copy_assets(root)
    print("S24U_IMAGE_HARNESS_H6_CONDITIONING_INFLUENCE_PATCH_APPLIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
