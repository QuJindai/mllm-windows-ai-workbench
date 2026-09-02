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
    text = replace_once(text, "versionCode = 7403", "versionCode = 7404", "H4 versionCode")
    text = replace_once(
        text,
        'versionName = "2.8.1-s24u-h3"',
        'versionName = "2.8.1-s24u-h4"',
        "H4 versionName",
    )
    path.write_text(text, encoding="utf-8")


def patch_text_encoder(root: Path) -> None:
    path = root / "app/src/main/cpp/src/TextEncoder.hpp"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "inline constexpr int kS24uClipChunks = 4;",
        "inline constexpr int kS24uClipChunks = 8;",
        "H4 eight chunks",
    )

    anchor = "  std::vector<std::string> splitPromptChunks(\n"
    helper = r'''  // Count the actual prompt content tokens after prompt-weight syntax has
  // been parsed away. This matches the units used by the fixed-77 CLIP passes
  // more closely than tokenizing the raw parenthesis/weight syntax itself.
  int promptContentTokenCount(const std::string &prompt_text) {
    if (!tokenizer_) return 0;
    if (anima_) return static_cast<int>(tokenizer_->Encode(prompt_text).size());

    auto parsed = promptProcessor_.process(prompt_text);
    int total = 0;
    const int dim1 = 768;
    const int dim2 = text_embedding_size_2;
    for (const auto &token : parsed) {
      if (token.is_embedding) {
        if (!token.embedding_data.empty())
          total += static_cast<int>(token.embedding_data.size()) / dim1;
        else if (sdxl_ && !token.embedding_data_2.empty())
          total += static_cast<int>(token.embedding_data_2.size()) / dim2;
      } else {
        total += static_cast<int>(tokenizer_->Encode(token.text).size());
      }
    }
    return total;
  }

'''
    text = replace_once(text, anchor, helper + anchor, "prompt content token counter")
    path.write_text(text, encoding="utf-8")


def patch_main_cpp(root: Path) -> None:
    path = root / "app/src/main/cpp/src/main.cpp"
    text = path.read_text(encoding="utf-8")

    phase_anchor = '''              std::string phase = "prompt";
              nlohmann::json prompt_trace = {
'''
    budget = r'''              std::vector<int> positive_chunk_tokens;
              std::vector<int> negative_chunk_tokens;
              int positive_input_tokens = static_cast<int>(positive_token_ids.size());
              int negative_input_tokens = static_cast<int>(negative_token_ids.size());
              int positive_effective_tokens = 0;
              int negative_effective_tokens = 0;
              if (text_encoder) {
                positive_input_tokens =
                    text_encoder->promptContentTokenCount(req->prompt);
                negative_input_tokens =
                    text_encoder->promptContentTokenCount(req->negative_prompt);
                for (const auto &chunk : positive_chunks) {
                  int count = text_encoder->promptContentTokenCount(chunk);
                  positive_chunk_tokens.push_back(count);
                  positive_effective_tokens += count;
                }
                for (const auto &chunk : negative_chunks) {
                  int count = text_encoder->promptContentTokenCount(chunk);
                  negative_chunk_tokens.push_back(count);
                  negative_effective_tokens += count;
                }
              }
              const int positive_truncated_tokens =
                  std::max(0, positive_input_tokens - positive_effective_tokens);
              const int negative_truncated_tokens =
                  std::max(0, negative_input_tokens - negative_effective_tokens);

              std::string phase = "prompt";
              nlohmann::json prompt_trace = {
'''
    text = replace_once(text, phase_anchor, budget, "prompt budget computation")

    json_anchor = '''                  {"negative_chunks", negative_chunks},
                  {"chunk_count", std::max(positive_chunks.size(),
                                             negative_chunks.size())},
                  {"duration_ms", 0},
'''
    json_new = '''                  {"negative_chunks", negative_chunks},
                  {"positive_input_tokens", positive_input_tokens},
                  {"positive_effective_tokens", positive_effective_tokens},
                  {"positive_truncated_tokens", positive_truncated_tokens},
                  {"negative_input_tokens", negative_input_tokens},
                  {"negative_effective_tokens", negative_effective_tokens},
                  {"negative_truncated_tokens", negative_truncated_tokens},
                  {"positive_chunk_tokens", positive_chunk_tokens},
                  {"negative_chunk_tokens", negative_chunk_tokens},
                  {"max_chunks", kS24uClipChunks},
                  {"chunk_count", std::max(positive_chunks.size(),
                                             negative_chunks.size())},
                  {"duration_ms", 0},
'''
    text = replace_once(text, json_anchor, json_new, "prompt budget JSON")
    path.write_text(text, encoding="utf-8")


def patch_service(root: Path) -> None:
    path = root / "app/src/main/java/io/github/xororz/localdream/service/BackgroundGenerationService.kt"
    text = path.read_text(encoding="utf-8")

    event_anchor = '''        val positiveChunks: List<String> = emptyList(),
        val negativeChunks: List<String> = emptyList(),
    )
'''
    event_new = '''        val positiveChunks: List<String> = emptyList(),
        val negativeChunks: List<String> = emptyList(),
        val positiveInputTokens: Int = 0,
        val positiveEffectiveTokens: Int = 0,
        val positiveTruncatedTokens: Int = 0,
        val negativeInputTokens: Int = 0,
        val negativeEffectiveTokens: Int = 0,
        val negativeTruncatedTokens: Int = 0,
        val positiveChunkTokens: List<Int> = emptyList(),
        val negativeChunkTokens: List<Int> = emptyList(),
        val maxChunks: Int = 8,
    )
'''
    text = replace_once(text, event_anchor, event_new, "H4 event budget fields")

    snapshot_anchor = '''        val positiveChunks: List<String> = emptyList(),
        val negativeChunks: List<String> = emptyList(),
    )

    sealed class GenerationState {
'''
    snapshot_new = '''        val positiveChunks: List<String> = emptyList(),
        val negativeChunks: List<String> = emptyList(),
        val schedulerSeen: Boolean = false,
        val unetSeen: Boolean = false,
        val traceProgress: Float = 0f,
        val positiveInputTokens: Int = 0,
        val positiveEffectiveTokens: Int = 0,
        val positiveTruncatedTokens: Int = 0,
        val negativeInputTokens: Int = 0,
        val negativeEffectiveTokens: Int = 0,
        val negativeTruncatedTokens: Int = 0,
        val positiveChunkTokens: List<Int> = emptyList(),
        val negativeChunkTokens: List<Int> = emptyList(),
        val maxChunks: Int = 8,
    )

    sealed class GenerationState {
'''
    text = replace_once(text, snapshot_anchor, snapshot_new, "H4 snapshot fields")

    parse_anchor = '''            positiveChunks = jsonStringList(message, "positive_chunks"),
            negativeChunks = jsonStringList(message, "negative_chunks"),
        )
'''
    parse_new = '''            positiveChunks = jsonStringList(message, "positive_chunks"),
            negativeChunks = jsonStringList(message, "negative_chunks"),
            positiveInputTokens = message.optInt("positive_input_tokens", 0),
            positiveEffectiveTokens = message.optInt("positive_effective_tokens", 0),
            positiveTruncatedTokens = message.optInt("positive_truncated_tokens", 0),
            negativeInputTokens = message.optInt("negative_input_tokens", 0),
            negativeEffectiveTokens = message.optInt("negative_effective_tokens", 0),
            negativeTruncatedTokens = message.optInt("negative_truncated_tokens", 0),
            positiveChunkTokens = jsonIntList(message, "positive_chunk_tokens"),
            negativeChunkTokens = jsonIntList(message, "negative_chunk_tokens"),
            maxChunks = message.optInt("max_chunks", 8).coerceAtLeast(1),
        )
'''
    text = replace_once(text, parse_anchor, parse_new, "H4 event parser")

    copy_anchor = '''            chunkCount = event.chunkCount,
            skipUncond = event.skipUncond,
            latentWidth = if (event.latentWidth > 0) event.latentWidth else previous.latentWidth,
            latentHeight = if (event.latentHeight > 0) event.latentHeight else previous.latentHeight,
            seqLen = if (event.seqLen > 0) event.seqLen else previous.seqLen,
            hiddenDim = if (event.hiddenDim > 0) event.hiddenDim else previous.hiddenDim,
            positiveTokenIds = event.positiveTokenIds.ifEmpty { previous.positiveTokenIds },
            negativeTokenIds = event.negativeTokenIds.ifEmpty { previous.negativeTokenIds },
            positiveChunks = event.positiveChunks.ifEmpty { previous.positiveChunks },
            negativeChunks = event.negativeChunks.ifEmpty { previous.negativeChunks },
        )
        next = when (event.phase) {
            "clip" -> next.copy(clipMs = event.durationMs)
            "unet_step" -> next.copy(latestUnetMs = event.durationMs)
            "scheduler_step" -> next.copy(latestSchedulerMs = event.durationMs)
            "vae_decode" -> next.copy(vaeMs = event.durationMs)
            "complete" -> next.copy(totalMs = event.durationMs)
            else -> next
        }
'''
    copy_new = '''            chunkCount = event.chunkCount,
            skipUncond = if (event.phase == "unet_step") event.skipUncond else previous.skipUncond,
            latentWidth = if (event.latentWidth > 0) event.latentWidth else previous.latentWidth,
            latentHeight = if (event.latentHeight > 0) event.latentHeight else previous.latentHeight,
            seqLen = if (event.seqLen > 0) event.seqLen else previous.seqLen,
            hiddenDim = if (event.hiddenDim > 0) event.hiddenDim else previous.hiddenDim,
            positiveTokenIds = event.positiveTokenIds.ifEmpty { previous.positiveTokenIds },
            negativeTokenIds = event.negativeTokenIds.ifEmpty { previous.negativeTokenIds },
            positiveChunks = event.positiveChunks.ifEmpty { previous.positiveChunks },
            negativeChunks = event.negativeChunks.ifEmpty { previous.negativeChunks },
            positiveInputTokens = if (event.phase == "prompt") event.positiveInputTokens else previous.positiveInputTokens,
            positiveEffectiveTokens = if (event.phase == "prompt") event.positiveEffectiveTokens else previous.positiveEffectiveTokens,
            positiveTruncatedTokens = if (event.phase == "prompt") event.positiveTruncatedTokens else previous.positiveTruncatedTokens,
            negativeInputTokens = if (event.phase == "prompt") event.negativeInputTokens else previous.negativeInputTokens,
            negativeEffectiveTokens = if (event.phase == "prompt") event.negativeEffectiveTokens else previous.negativeEffectiveTokens,
            negativeTruncatedTokens = if (event.phase == "prompt") event.negativeTruncatedTokens else previous.negativeTruncatedTokens,
            positiveChunkTokens = event.positiveChunkTokens.ifEmpty { previous.positiveChunkTokens },
            negativeChunkTokens = event.negativeChunkTokens.ifEmpty { previous.negativeChunkTokens },
            maxChunks = if (event.phase == "prompt") event.maxChunks else previous.maxChunks,
        )
        val diffusionProgress = if (event.diffusionTotal > 0 && event.diffusionStep > 0) {
            (event.diffusionStep.toFloat() / event.diffusionTotal.toFloat())
                .coerceIn(0f, 1f)
                .coerceAtLeast(next.traceProgress)
        } else {
            next.traceProgress
        }
        next = when (event.phase) {
            "clip" -> next.copy(clipMs = event.durationMs)
            "unet_step" -> next.copy(
                latestUnetMs = event.durationMs,
                unetSeen = true,
                traceProgress = diffusionProgress,
            )
            "scheduler_step" -> next.copy(
                latestSchedulerMs = event.durationMs,
                schedulerSeen = true,
                traceProgress = diffusionProgress,
            )
            "vae_decode" -> next.copy(
                vaeMs = event.durationMs,
                traceProgress = 0.98f.coerceAtLeast(next.traceProgress),
            )
            "complete" -> next.copy(totalMs = event.durationMs, traceProgress = 1f)
            else -> next
        }
'''
    text = replace_once(text, copy_anchor, copy_new, "H4 truthful reducer")

    complete_anchor = '''                                    _microscopeState.value = _microscopeState.value.copy(
                                        phase = "complete",
                                        totalMs = totalMs,
                                        firstStepMs = firstStepMs,
                                    )
'''
    complete_new = '''                                    _microscopeState.value = _microscopeState.value.copy(
                                        phase = "complete",
                                        totalMs = totalMs,
                                        firstStepMs = firstStepMs,
                                        traceProgress = 1f,
                                    )
'''
    text = replace_once(text, complete_anchor, complete_new, "complete progress 100")
    path.write_text(text, encoding="utf-8")


def patch_screen(root: Path) -> None:
    path = root / "app/src/main/java/io/github/xororz/localdream/ui/screens/ModelRunScreen.kt"
    text = path.read_text(encoding="utf-8")

    import_anchor = "import android.widget.Toast\n"
    import_new = '''import android.widget.Toast
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
'''
    text = replace_once(text, import_anchor, import_new, "WebView imports")
    text = replace_once(
        text,
        "import androidx.compose.ui.unit.dp\n",
        "import androidx.compose.ui.unit.dp\nimport androidx.compose.ui.viewinterop.AndroidView\n",
        "AndroidView import",
    )
    text = replace_once(
        text,
        "import java.io.File\n",
        "import java.io.ByteArrayInputStream\nimport java.io.File\n",
        "ByteArrayInputStream import",
    )
    text = replace_once(
        text,
        "import kotlinx.coroutines.withTimeoutOrNull\n",
        "import kotlinx.coroutines.withTimeoutOrNull\nimport org.json.JSONArray\nimport org.json.JSONObject\n",
        "JSON imports",
    )

    start_marker = "    @Composable\n    fun MicroscopePage() {"
    end_marker = "\n\n    @Composable\n    fun PromptPage() {"
    start = text.find(start_marker)
    end = text.find(end_marker, start)
    if start < 0 or end < 0:
        raise RuntimeError("H4 microscope function boundary not found")

    function = r'''    @SuppressLint("SetJavaScriptEnabled")
    @Composable
    fun MicroscopePage() {
        // S24U_H4_VISUAL_MICROSCOPE
        var pageReady by remember { mutableStateOf(false) }
        var webError by remember { mutableStateOf<String?>(null) }

        fun intArrayJson(values: List<Int>): JSONArray = JSONArray().apply {
            values.forEach { put(it) }
        }

        fun stringArrayJson(values: List<String>): JSONArray = JSONArray().apply {
            values.forEach { put(it) }
        }

        fun eventJson(event: BackgroundGenerationService.MicroscopeEvent): JSONObject = JSONObject().apply {
            put("phase", event.phase)
            put("step", event.step)
            put("total_steps", event.totalSteps)
            put("diffusion_step", event.diffusionStep)
            put("diffusion_total", event.diffusionTotal)
            put("timestep", event.timestep.toDouble())
            put("duration_ms", event.durationMs)
            put("elapsed_ms", event.elapsedMs)
            put("chunk_count", event.chunkCount)
            put("skip_uncond", event.skipUncond)
            put("latent_width", event.latentWidth)
            put("latent_height", event.latentHeight)
            put("seq_len", event.seqLen)
            put("hidden_dim", event.hiddenDim)
        }

        val payload = JSONObject().apply {
            put("phase", microscope.phase)
            put("trace_progress", microscope.traceProgress.toDouble())
            put("backend", if (model?.runOnCpu == true) "CPU/MNN" else "NPU/QNN")
            put("width", currentWidth)
            put("height", currentHeight)
            put("scheduler", scheduler)
            put("steps", steps.roundToInt())
            put("cfg", cfg.toDouble())
            put("latest_unet_ms", microscope.latestUnetMs)
            put("latest_scheduler_ms", microscope.latestSchedulerMs)
            put("clip_ms", microscope.clipMs)
            put("vae_ms", microscope.vaeMs)
            put("total_ms", microscope.totalMs)
            put("first_step_ms", microscope.firstStepMs)
            put("diffusion_step", microscope.diffusionStep)
            put("diffusion_total", microscope.diffusionTotal)
            put("timestep", microscope.timestep.toDouble())
            put("chunk_count", microscope.chunkCount)
            put("skip_uncond", microscope.skipUncond)
            put("scheduler_seen", microscope.schedulerSeen)
            put("unet_seen", microscope.unetSeen)
            put("latent_width", microscope.latentWidth)
            put("latent_height", microscope.latentHeight)
            put("seq_len", microscope.seqLen)
            put("hidden_dim", microscope.hiddenDim)
            put("positive_token_ids", intArrayJson(microscope.positiveTokenIds))
            put("negative_token_ids", intArrayJson(microscope.negativeTokenIds))
            put("positive_chunks", stringArrayJson(microscope.positiveChunks))
            put("negative_chunks", stringArrayJson(microscope.negativeChunks))
            put("positive_input_tokens", microscope.positiveInputTokens)
            put("positive_effective_tokens", microscope.positiveEffectiveTokens)
            put("positive_truncated_tokens", microscope.positiveTruncatedTokens)
            put("negative_input_tokens", microscope.negativeInputTokens)
            put("negative_effective_tokens", microscope.negativeEffectiveTokens)
            put("negative_truncated_tokens", microscope.negativeTruncatedTokens)
            put("positive_chunk_tokens", intArrayJson(microscope.positiveChunkTokens))
            put("negative_chunk_tokens", intArrayJson(microscope.negativeChunkTokens))
            put("max_chunks", microscope.maxChunks)
            put("events", JSONArray().apply { microscope.events.forEach { put(eventJson(it)) } })
        }.toString()

        Box(modifier = Modifier.fillMaxSize()) {
            AndroidView(
                modifier = Modifier.fillMaxSize(),
                factory = { androidContext ->
                    WebView(androidContext).apply {
                        setBackgroundColor(android.graphics.Color.TRANSPARENT)
                        settings.javaScriptEnabled = true
                        settings.domStorageEnabled = false
                        settings.allowContentAccess = false
                        settings.allowFileAccess = true
                        settings.allowUniversalAccessFromFileURLs = false
                        settings.allowFileAccessFromFileURLs = false
                        settings.mixedContentMode = WebSettings.MIXED_CONTENT_NEVER_ALLOW
                        webViewClient = object : WebViewClient() {
                            private fun allowed(url: String?): Boolean =
                                url?.startsWith("file:///android_asset/s24u_microscope/") == true

                            override fun shouldOverrideUrlLoading(
                                view: WebView?,
                                request: WebResourceRequest?,
                            ): Boolean = !allowed(request?.url?.toString())

                            override fun shouldInterceptRequest(
                                view: WebView?,
                                request: WebResourceRequest?,
                            ): WebResourceResponse? {
                                val url = request?.url?.toString()
                                if (allowed(url)) return super.shouldInterceptRequest(view, request)
                                return WebResourceResponse(
                                    "text/plain",
                                    "utf-8",
                                    ByteArrayInputStream(ByteArray(0)),
                                )
                            }

                            override fun onPageFinished(view: WebView?, url: String?) {
                                if (allowed(url)) {
                                    pageReady = true
                                    webError = null
                                }
                            }

                            override fun onReceivedError(
                                view: WebView?,
                                request: WebResourceRequest?,
                                error: android.webkit.WebResourceError?,
                            ) {
                                if (request?.isForMainFrame == true) {
                                    webError = error?.description?.toString() ?: "WebView load error"
                                }
                            }
                        }
                        loadUrl("file:///android_asset/s24u_microscope/index.html")
                    }
                },
                update = { webView ->
                    if (pageReady) {
                        webView.evaluateJavascript(
                            "window.S24UMicroscope && window.S24UMicroscope.update($payload);",
                            null,
                        )
                    }
                },
            )

            webError?.let { message ->
                Card(
                    modifier = Modifier.fillMaxWidth().padding(16.dp),
                    colors = CardDefaults.cardColors(
                        containerColor = MaterialTheme.colorScheme.errorContainer,
                    ),
                ) {
                    Column(
                        modifier = Modifier.padding(16.dp),
                        verticalArrangement = Arrangement.spacedBy(6.dp),
                    ) {
                        Text("H4 显微镜加载失败", fontWeight = FontWeight.Bold)
                        Text(message, style = MaterialTheme.typography.bodySmall)
                        Text(
                            "真实 native trace 仍保留在 BackgroundGenerationService.microscopeState。",
                            style = MaterialTheme.typography.bodySmall,
                        )
                    }
                }
            }
        }
    }'''
    text = text[:start] + function + text[end:]
    path.write_text(text, encoding="utf-8")


def copy_assets(root: Path) -> None:
    src = Path(__file__).resolve().parent / "h4_assets" / "microscope"
    dst = root / "app/src/main/assets/s24u_microscope"
    if not (src / "index.html").is_file() or not (src / "microscope.css").is_file() or not (src / "microscope.js").is_file():
        raise RuntimeError("H4 microscope assets incomplete")
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: patch_h4.py <h3-patched-local-dream-root>", file=sys.stderr)
        return 2
    root = Path(sys.argv[1]).resolve()
    patch_gradle(root)
    patch_text_encoder(root)
    patch_main_cpp(root)
    patch_service(root)
    patch_screen(root)
    copy_assets(root)
    print("S24U_IMAGE_HARNESS_H4_VISUAL_MICROSCOPE_PATCH_APPLIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
