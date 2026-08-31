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


def regex_once(text: str, pattern: str, repl: str, label: str, flags: int = 0) -> str:
    updated, count = re.subn(pattern, repl, text, count=1, flags=flags)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one regex match, found {count}")
    return updated


def patch_gradle(root: Path) -> None:
    path = root / "app/build.gradle.kts"
    text = path.read_text(encoding="utf-8")
    text = replace_once(text, "versionCode = 7402", "versionCode = 7403", "H3 versionCode")
    text = replace_once(
        text,
        'versionName = "2.8.1-s24u-h2"',
        'versionName = "2.8.1-s24u-h3"',
        "H3 versionName",
    )
    path.write_text(text, encoding="utf-8")


def patch_pipeline(root: Path) -> None:
    path = root / "app/src/main/cpp/src/Pipeline.hpp"
    text = path.read_text(encoding="utf-8")

    if "#include <cstdint>" not in text:
        text = replace_once(text, "#include <cstring>\n", "#include <cstring>\n#include <cstdint>\n", "cstdint include")

    old_callback = "// step / total_steps / optional base64 preview image.\nusing ProgressCallback = std::function<void(int, int, const std::string &)>;\n"
    trace_types = r'''// step / total_steps / optional base64 preview image.
using ProgressCallback = std::function<void(int, int, const std::string &)>;

// S24U H3 microscope: real runtime evidence emitted from the native pipeline.
// This is deliberately stage/step telemetry rather than a simulated animation.
// It exposes timing and tensor-shape metadata without copying hidden tensors out
// of the QNN runtime (which would materially change memory/performance behavior).
struct MicroscopeTraceEvent {
  std::string phase;
  int step = 0;
  int total_steps = 0;
  int diffusion_step = 0;
  int diffusion_total = 0;
  float timestep = 0.0f;
  int chunk_count = 1;
  int64_t duration_ms = 0;
  int64_t elapsed_ms = 0;
  bool skip_uncond = false;
  int latent_width = 0;
  int latent_height = 0;
  int seq_len = 0;
  int hidden_dim = 0;
};
using MicroscopeTraceCallback =
    std::function<void(const MicroscopeTraceEvent &)>;

'''
    text = replace_once(text, old_callback, trace_types, "microscope trace types")

    text = replace_once(
        text,
        "  GenerationResult generate(GenerationRequest &req,\n                            const ProgressCallback &progress_callback);\n",
        "  GenerationResult generate(\n"
        "      GenerationRequest &req, const ProgressCallback &progress_callback,\n"
        "      const MicroscopeTraceCallback &microscope_callback = {});\n",
        "generate declaration",
    )

    text = replace_once(
        text,
        "inline GenerationResult Pipeline::generate(\n    GenerationRequest &req, const ProgressCallback &progress_callback) {",
        "inline GenerationResult Pipeline::generate(\n"
        "    GenerationRequest &req, const ProgressCallback &progress_callback,\n"
        "    const MicroscopeTraceCallback &microscope_callback) {",
        "generate definition",
    )

    text = replace_once(
        text,
        "    auto start_time = std::chrono::high_resolution_clock::now();\n"
        "    int first_step_time_ms = 0;",
        "    auto start_time = std::chrono::high_resolution_clock::now();\n"
        "    auto emit_trace = [&](MicroscopeTraceEvent event) {\n"
        "      event.elapsed_ms = elapsedMs(start_time);\n"
        "      if (microscope_callback) microscope_callback(event);\n"
        "    };\n"
        "    int first_step_time_ms = 0;",
        "trace emitter",
    )

    # H2 already converted the single Conditioning into conds + front reference.
    clip_old = '''    auto clip_start = std::chrono::high_resolution_clock::now();
    std::vector<Conditioning> conds = encodePromptChunks(req);
    Conditioning &cond = conds.front();
    std::cout << "CLIP dur: " << elapsedMs(clip_start) << "ms\\n";
    current_step++;
'''
    clip_new = '''    auto clip_start = std::chrono::high_resolution_clock::now();
    std::vector<Conditioning> conds = encodePromptChunks(req);
    Conditioning &cond = conds.front();
    auto clip_dur = elapsedMs(clip_start);
    std::cout << "CLIP dur: " << clip_dur << "ms\\n";
    MicroscopeTraceEvent clip_trace;
    clip_trace.phase = "clip";
    clip_trace.step = current_step + 1;
    clip_trace.total_steps = total_run_steps;
    clip_trace.chunk_count = static_cast<int>(conds.size());
    clip_trace.duration_ms = clip_dur;
    clip_trace.seq_len = cond.seq_len;
    clip_trace.hidden_dim = cond.hidden_dim;
    clip_trace.latent_width = sample_width;
    clip_trace.latent_height = sample_height;
    emit_trace(clip_trace);
    current_step++;
'''
    text = replace_once(text, clip_old, clip_new, "CLIP trace")

    unet_old = '''      auto step_dur = elapsedMs(step_start_time);
      if (i == start_step) first_step_time_ms = (int)step_dur;
      std::cout << "UNET step " << i << " dur: " << step_dur << "ms\\n";
'''
    unet_new = '''      auto step_dur = elapsedMs(step_start_time);
      if (i == start_step) first_step_time_ms = (int)step_dur;
      std::cout << "UNET step " << i << " dur: " << step_dur << "ms\\n";
      MicroscopeTraceEvent unet_trace;
      unet_trace.phase = "unet_step";
      unet_trace.step = current_step;
      unet_trace.total_steps = total_run_steps;
      unet_trace.diffusion_step = i - start_step + 1;
      unet_trace.diffusion_total = static_cast<int>(timesteps.size()) - start_step;
      unet_trace.timestep = current_ts;
      unet_trace.chunk_count = static_cast<int>(conds.size());
      unet_trace.duration_ms = step_dur;
      unet_trace.skip_uncond = skip_uncond;
      unet_trace.latent_width = sample_width;
      unet_trace.latent_height = sample_height;
      unet_trace.seq_len = cond.seq_len;
      unet_trace.hidden_dim = cond.hidden_dim;
      emit_trace(unet_trace);
'''
    text = replace_once(text, unet_old, unet_new, "UNet trace")

    scheduler_old = "      latents = scheduler->step(noise_pred, timesteps(i), latents).prev_sample;\n"
    scheduler_new = '''      auto scheduler_start = std::chrono::high_resolution_clock::now();
      latents = scheduler->step(noise_pred, timesteps(i), latents).prev_sample;
      auto scheduler_dur = elapsedMs(scheduler_start);
      MicroscopeTraceEvent scheduler_trace;
      scheduler_trace.phase = "scheduler_step";
      scheduler_trace.step = current_step;
      scheduler_trace.total_steps = total_run_steps;
      scheduler_trace.diffusion_step = i - start_step + 1;
      scheduler_trace.diffusion_total = static_cast<int>(timesteps.size()) - start_step;
      scheduler_trace.timestep = current_ts;
      scheduler_trace.chunk_count = static_cast<int>(conds.size());
      scheduler_trace.duration_ms = scheduler_dur;
      scheduler_trace.latent_width = sample_width;
      scheduler_trace.latent_height = sample_height;
      emit_trace(scheduler_trace);
'''
    text = replace_once(text, scheduler_old, scheduler_new, "scheduler trace")

    vae_old = '''    std::cout << "VAE Dec dur: " << elapsedMs(vae_dec_start) << "ms\\n";
'''
    vae_new = '''    auto vae_dec_dur = elapsedMs(vae_dec_start);
    std::cout << "VAE Dec dur: " << vae_dec_dur << "ms\\n";
    MicroscopeTraceEvent vae_trace;
    vae_trace.phase = "vae_decode";
    vae_trace.step = current_step + 1;
    vae_trace.total_steps = total_run_steps;
    vae_trace.chunk_count = static_cast<int>(conds.size());
    vae_trace.duration_ms = vae_dec_dur;
    vae_trace.latent_width = sample_width;
    vae_trace.latent_height = sample_height;
    emit_trace(vae_trace);
'''
    text = replace_once(text, vae_old, vae_new, "VAE trace")

    complete_old = '''    auto total_time = elapsedMs(start_time);

    // SDXL aspect-ratio padded inpaint: crop the centered target region out
'''
    complete_new = '''    auto total_time = elapsedMs(start_time);
    MicroscopeTraceEvent complete_trace;
    complete_trace.phase = "complete";
    complete_trace.step = current_step;
    complete_trace.total_steps = total_run_steps;
    complete_trace.chunk_count = static_cast<int>(conds.size());
    complete_trace.duration_ms = total_time;
    complete_trace.latent_width = sample_width;
    complete_trace.latent_height = sample_height;
    emit_trace(complete_trace);

    // SDXL aspect-ratio padded inpaint: crop the centered target region out
'''
    text = replace_once(text, complete_old, complete_new, "complete trace")

    marker_anchor = "// S24U H3 microscope: real runtime evidence emitted from the native pipeline."
    if marker_anchor not in text:
        raise RuntimeError("H3 native marker missing after patch")
    path.write_text(text, encoding="utf-8")


def patch_main_cpp(root: Path) -> None:
    path = root / "app/src/main/cpp/src/main.cpp"
    text = path.read_text(encoding="utf-8")

    text = replace_once(
        text,
        "static void registerGenerateEndpoint(httplib::Server &svr, Pipeline *pipeline) {",
        "static void registerGenerateEndpoint(httplib::Server &svr, Pipeline *pipeline,\n"
        "                                     TextEncoder *text_encoder) {",
        "generate endpoint signature",
    )
    text = replace_once(
        text,
        "          [pipeline, req](intptr_t, httplib::DataSink &sink) -> bool {",
        "          [pipeline, req, text_encoder](intptr_t, httplib::DataSink &sink) -> bool {",
        "SSE provider capture",
    )

    prompt_anchor = '''              std::lock_guard<std::mutex> generation_lock(g_generation_mutex);
              auto result = pipeline->generate(
'''
    prompt_trace = r'''              std::lock_guard<std::mutex> generation_lock(g_generation_mutex);

              // H3 microscope prompt evidence is emitted from the exact request
              // that reaches the native backend. Token ids are raw tokenizer
              // content ids; chunk lists are the exact H2 fixed-77 text windows.
              std::vector<int> positive_token_ids;
              std::vector<int> negative_token_ids;
              std::vector<std::string> positive_chunks{req->prompt};
              std::vector<std::string> negative_chunks{req->negative_prompt};
              if (text_encoder && text_encoder->tokenizer()) {
                positive_token_ids = text_encoder->tokenizer()->Encode(req->prompt);
                negative_token_ids =
                    text_encoder->tokenizer()->Encode(req->negative_prompt);
                if (!text_encoder->isAnima()) {
                  positive_chunks = text_encoder->splitPromptChunks(req->prompt);
                  negative_chunks =
                      text_encoder->splitPromptChunks(req->negative_prompt);
                }
              }
              std::string phase = "prompt";
              nlohmann::json prompt_trace = {
                  {"type", "trace"},
                  {"phase", phase},
                  {"positive_token_ids", positive_token_ids},
                  {"negative_token_ids", negative_token_ids},
                  {"positive_token_count", positive_token_ids.size()},
                  {"negative_token_count", negative_token_ids.size()},
                  {"positive_chunks", positive_chunks},
                  {"negative_chunks", negative_chunks},
                  {"chunk_count", std::max(positive_chunks.size(),
                                             negative_chunks.size())},
                  {"duration_ms", 0},
                  {"elapsed_ms", 0}};
              std::string prompt_ev =
                  "event: trace\ndata: " + prompt_trace.dump() + "\n\n";
              if (!sink.is_writable() ||
                  !sink.write(prompt_ev.c_str(), prompt_ev.size()))
                throw std::runtime_error(
                    "Client disconnected before microscope prompt trace");

              auto result = pipeline->generate(
'''
    text = replace_once(text, prompt_anchor, prompt_trace, "prompt trace SSE")

    close_anchor = '''                  });
              auto enc_start = std::chrono::high_resolution_clock::now();
'''
    trace_callback = r'''                  },
                  [&sink](const MicroscopeTraceEvent &trace) {
                    nlohmann::json m = {
                        {"type", "trace"},
                        {"phase", trace.phase},
                        {"step", trace.step},
                        {"total_steps", trace.total_steps},
                        {"diffusion_step", trace.diffusion_step},
                        {"diffusion_total", trace.diffusion_total},
                        {"timestep", trace.timestep},
                        {"chunk_count", trace.chunk_count},
                        {"duration_ms", trace.duration_ms},
                        {"elapsed_ms", trace.elapsed_ms},
                        {"skip_uncond", trace.skip_uncond},
                        {"latent_width", trace.latent_width},
                        {"latent_height", trace.latent_height},
                        {"seq_len", trace.seq_len},
                        {"hidden_dim", trace.hidden_dim}};
                    std::string ev =
                        "event: trace\ndata: " + m.dump() + "\n\n";
                    if (!sink.is_writable() ||
                        !sink.write(ev.c_str(), ev.size()))
                      throw std::runtime_error(
                          "Client disconnected, microscope trace aborted");
                  });
              auto enc_start = std::chrono::high_resolution_clock::now();
'''
    text = replace_once(text, close_anchor, trace_callback, "native trace SSE callback")

    text = replace_once(
        text,
        "  if (pipeline) registerGenerateEndpoint(svr, pipeline.get());",
        "  if (pipeline)\n"
        "    registerGenerateEndpoint(svr, pipeline.get(), text_encoder.get());",
        "generate endpoint registration",
    )
    path.write_text(text, encoding="utf-8")


def patch_service(root: Path) -> None:
    path = root / "app/src/main/java/io/github/xororz/localdream/service/BackgroundGenerationService.kt"
    text = path.read_text(encoding="utf-8")

    state_anchor = '''        private val _generationState = MutableStateFlow<GenerationState>(GenerationState.Idle)
        val generationState: StateFlow<GenerationState> = _generationState

        private val _bitmapConsumed = MutableStateFlow(false)
'''
    state_new = '''        private val _generationState = MutableStateFlow<GenerationState>(GenerationState.Idle)
        val generationState: StateFlow<GenerationState> = _generationState

        private val _microscopeState = MutableStateFlow(MicroscopeSnapshot())
        val microscopeState: StateFlow<MicroscopeSnapshot> = _microscopeState

        private val _bitmapConsumed = MutableStateFlow(false)
'''
    text = replace_once(text, state_anchor, state_new, "microscope StateFlow")

    classes_anchor = '''    sealed class GenerationState {
'''
    classes = r'''    data class MicroscopeEvent(
        val phase: String,
        val step: Int = 0,
        val totalSteps: Int = 0,
        val diffusionStep: Int = 0,
        val diffusionTotal: Int = 0,
        val timestep: Float = 0f,
        val durationMs: Long = 0L,
        val elapsedMs: Long = 0L,
        val chunkCount: Int = 1,
        val skipUncond: Boolean = false,
        val latentWidth: Int = 0,
        val latentHeight: Int = 0,
        val seqLen: Int = 0,
        val hiddenDim: Int = 0,
        val positiveTokenIds: List<Int> = emptyList(),
        val negativeTokenIds: List<Int> = emptyList(),
        val positiveChunks: List<String> = emptyList(),
        val negativeChunks: List<String> = emptyList(),
    )

    data class MicroscopeSnapshot(
        val phase: String = "idle",
        val events: List<MicroscopeEvent> = emptyList(),
        val latestUnetMs: Long = 0L,
        val latestSchedulerMs: Long = 0L,
        val clipMs: Long = 0L,
        val vaeMs: Long = 0L,
        val totalMs: Long = 0L,
        val firstStepMs: Long = 0L,
        val diffusionStep: Int = 0,
        val diffusionTotal: Int = 0,
        val timestep: Float = 0f,
        val chunkCount: Int = 1,
        val skipUncond: Boolean = false,
        val latentWidth: Int = 0,
        val latentHeight: Int = 0,
        val seqLen: Int = 0,
        val hiddenDim: Int = 0,
        val positiveTokenIds: List<Int> = emptyList(),
        val negativeTokenIds: List<Int> = emptyList(),
        val positiveChunks: List<String> = emptyList(),
        val negativeChunks: List<String> = emptyList(),
    )

    sealed class GenerationState {
'''
    text = replace_once(text, classes_anchor, classes, "microscope data classes")

    helper_anchor = '''    // Expands packed RGB bytes into ARGB ints; stops at whichever buffer ends
'''
    helpers = r'''    private fun jsonIntList(message: JSONObject, key: String): List<Int> {
        val array = message.optJSONArray(key) ?: return emptyList()
        return List(array.length()) { index -> array.optInt(index) }
    }

    private fun jsonStringList(message: JSONObject, key: String): List<String> {
        val array = message.optJSONArray(key) ?: return emptyList()
        return List(array.length()) { index -> array.optString(index) }
    }

    private fun appendMicroscopeTrace(message: JSONObject) {
        val event = MicroscopeEvent(
            phase = message.optString("phase", "unknown"),
            step = message.optInt("step", 0),
            totalSteps = message.optInt("total_steps", 0),
            diffusionStep = message.optInt("diffusion_step", 0),
            diffusionTotal = message.optInt("diffusion_total", 0),
            timestep = message.optDouble("timestep", 0.0).toFloat(),
            durationMs = message.optLong("duration_ms", 0L),
            elapsedMs = message.optLong("elapsed_ms", 0L),
            chunkCount = message.optInt("chunk_count", 1).coerceAtLeast(1),
            skipUncond = message.optBoolean("skip_uncond", false),
            latentWidth = message.optInt("latent_width", 0),
            latentHeight = message.optInt("latent_height", 0),
            seqLen = message.optInt("seq_len", 0),
            hiddenDim = message.optInt("hidden_dim", 0),
            positiveTokenIds = jsonIntList(message, "positive_token_ids"),
            negativeTokenIds = jsonIntList(message, "negative_token_ids"),
            positiveChunks = jsonStringList(message, "positive_chunks"),
            negativeChunks = jsonStringList(message, "negative_chunks"),
        )
        val previous = _microscopeState.value
        var next = previous.copy(
            phase = event.phase,
            events = previous.events.takeLast(127) + event,
            diffusionStep = if (event.diffusionStep > 0) event.diffusionStep else previous.diffusionStep,
            diffusionTotal = if (event.diffusionTotal > 0) event.diffusionTotal else previous.diffusionTotal,
            timestep = if (event.diffusionStep > 0) event.timestep else previous.timestep,
            chunkCount = event.chunkCount,
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
        _microscopeState.value = next
    }

    // Expands packed RGB bytes into ARGB ints; stops at whichever buffer ends
'''
    text = replace_once(text, helper_anchor, helpers, "microscope parser helpers")

    text = replace_once(
        text,
        '''        try {
            updateState(GenerationState.Progress(0f))
''',
        '''        try {
            _microscopeState.value = MicroscopeSnapshot(phase = "starting")
            updateState(GenerationState.Progress(0f))
''',
        "reset microscope on generation start",
    )

    when_anchor = '''                            when (message.optString("type")) {
                                "progress" -> {
'''
    when_new = '''                            when (message.optString("type")) {
                                "trace" -> {
                                    appendMicroscopeTrace(message)
                                }

                                "progress" -> {
'''
    text = replace_once(text, when_anchor, when_new, "trace SSE parser")

    complete_extract = '''                                    val returnedSeed =
                                        message.optLong("seed", -1).takeIf { it != -1L }
                                    val resultWidth = message.optInt("width", 512)
'''
    complete_extract_new = '''                                    val returnedSeed =
                                        message.optLong("seed", -1).takeIf { it != -1L }
                                    val totalMs = message.optLong("generation_time_ms", 0L)
                                    val firstStepMs = message.optLong("first_step_time_ms", 0L)
                                    _microscopeState.value = _microscopeState.value.copy(
                                        phase = "complete",
                                        totalMs = totalMs,
                                        firstStepMs = firstStepMs,
                                    )
                                    val resultWidth = message.optInt("width", 512)
'''
    text = replace_once(text, complete_extract, complete_extract_new, "complete timing snapshot")

    error_anchor = '''                                "error" -> {
                                    val errorMsg =
                                        message.optString("message", "unknown error")
'''
    error_new = '''                                "error" -> {
                                    val errorMsg =
                                        message.optString("message", "unknown error")
                                    _microscopeState.value = _microscopeState.value.copy(phase = "error")
'''
    text = replace_once(text, error_anchor, error_new, "microscope error phase")

    path.write_text(text, encoding="utf-8")


def patch_screen(root: Path) -> None:
    path = root / "app/src/main/java/io/github/xororz/localdream/ui/screens/ModelRunScreen.kt"
    text = path.read_text(encoding="utf-8")

    text = replace_once(
        text,
        '''    val serviceState by BackgroundGenerationService.generationState.collectAsState()
    val backendState by BackendService.backendState.collectAsState()
''',
        '''    val serviceState by BackgroundGenerationService.generationState.collectAsState()
    val microscope by BackgroundGenerationService.microscopeState.collectAsState()
    val backendState by BackendService.backendState.collectAsState()
''',
        "microscope subscription",
    )

    text = replace_once(
        text,
        "    val pagerState = rememberPagerState(initialPage = 0, pageCount = { 3 })",
        "    val pagerState = rememberPagerState(initialPage = 0, pageCount = { 4 })",
        "four-page pager",
    )

    page_anchor = '''    // === Page Composable Functions ===
    @Composable
    fun PromptPage() {
'''
    microscope_page = r'''    // === Page Composable Functions ===
    @Composable
    fun MicroscopePage() {
        val recentEvents = microscope.events.takeLast(24)
        val positiveIds = microscope.positiveTokenIds.take(48).joinToString(" ")
        val negativeIds = microscope.negativeTokenIds.take(48).joinToString(" ")
        val activeBackend = if (model?.runOnCpu == true) "CPU/MNN" else "NPU/QNN"
        val phaseLabel = when (microscope.phase) {
            "prompt" -> "Prompt / Token"
            "clip" -> "CLIP 文本编码"
            "unet_step" -> "UNet 去噪"
            "scheduler_step" -> "Scheduler 更新"
            "vae_decode" -> "VAE 解码"
            "complete" -> "完成"
            "error" -> "错误"
            "starting" -> "启动"
            else -> microscope.phase
        }

        Column(
            modifier = Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 16.dp, vertical = 12.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            ElevatedCard(modifier = Modifier.fillMaxWidth()) {
                Column(
                    modifier = Modifier.padding(16.dp),
                    verticalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    Text("S24U IMAGE MICROSCOPE · LIVE", style = MaterialTheme.typography.titleMedium)
                    Text("当前阶段 → $phaseLabel", fontWeight = FontWeight.Bold)
                    Text("执行后端 → $activeBackend · ${currentWidth}×${currentHeight}")
                    Text("Scheduler → $scheduler · Steps ${steps.roundToInt()} · CFG $cfg")
                    Text("总进度 → ${(progress * 100).toInt()}% · 事件 ${microscope.events.size}")
                    if (microscope.totalMs > 0L) {
                        Text("最近一次总耗时 → ${microscope.totalMs} ms · First UNet ${microscope.firstStepMs} ms")
                    }
                }
            }

            ElevatedCard(modifier = Modifier.fillMaxWidth()) {
                Column(
                    modifier = Modifier.padding(16.dp),
                    verticalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    Text("Prompt / Token", style = MaterialTheme.typography.titleMedium)
                    Text("Positive → ${promptField.tokenCount}/${promptField.tokenMax} · chunks=${microscope.positiveChunks.size.coerceAtLeast(1)}")
                    Text("Negative → ${negativePromptField.tokenCount}/${negativePromptField.tokenMax} · chunks=${microscope.negativeChunks.size.coerceAtLeast(1)}")
                    Text("固定图形 → 每块 77 slots；有效长提示词由多块真实参与推理")
                    Text("Positive token IDs → ${positiveIds.ifBlank { "等待运行…" }}", style = MaterialTheme.typography.bodySmall)
                    Text("Negative token IDs → ${negativeIds.ifBlank { "(empty / 等待运行)" }}", style = MaterialTheme.typography.bodySmall)
                    microscope.positiveChunks.forEachIndexed { index, chunk ->
                        Text("P${index + 1} → $chunk", style = MaterialTheme.typography.bodySmall)
                    }
                    microscope.negativeChunks.forEachIndexed { index, chunk ->
                        Text("N${index + 1} → $chunk", style = MaterialTheme.typography.bodySmall)
                    }
                }
            }

            ElevatedCard(modifier = Modifier.fillMaxWidth()) {
                Column(
                    modifier = Modifier.padding(16.dp),
                    verticalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    Text("实时计算链", style = MaterialTheme.typography.titleMedium)
                    Text("1. Prompt/Tokenizer → ${if (microscope.positiveTokenIds.isNotEmpty()) "LIVE" else "WAIT"}")
                    Text("2. CLIP → ${if (microscope.clipMs > 0L) "${microscope.clipMs} ms" else "WAIT"} · seq=${microscope.seqLen} hidden=${microscope.hiddenDim}")
                    Text("3. UNet → ${if (microscope.latestUnetMs > 0L) "${microscope.latestUnetMs} ms" else "WAIT"}")
                    Text("4. Scheduler → ${if (microscope.latestSchedulerMs > 0L) "${microscope.latestSchedulerMs} ms" else "WAIT"}")
                    Text("5. VAE → ${if (microscope.vaeMs > 0L) "${microscope.vaeMs} ms" else "WAIT"}")
                    Text("Latent → ${microscope.latentWidth}×${microscope.latentHeight} · chunks=${microscope.chunkCount}")
                }
            }

            ElevatedCard(modifier = Modifier.fillMaxWidth()) {
                Column(
                    modifier = Modifier.padding(16.dp),
                    verticalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    Text("UNet / Scheduler", style = MaterialTheme.typography.titleMedium)
                    Text("Diffusion → ${microscope.diffusionStep}/${microscope.diffusionTotal}")
                    Text("Timestep → ${String.format(Locale.US, "%.2f", microscope.timestep)}")
                    Text("UNet → ${microscope.latestUnetMs} ms · Scheduler → ${microscope.latestSchedulerMs} ms")
                    Text("CFG=1 skip-uncond → ${microscope.skipUncond}")
                    Text("Condition chunks → ${microscope.chunkCount}")
                    intermediateBitmap?.let { bitmap ->
                        Spacer(modifier = Modifier.height(6.dp))
                        Card(
                            modifier = Modifier.fillMaxWidth().aspectRatio(1f),
                            shape = MaterialTheme.shapes.small,
                        ) {
                            Image(
                                bitmap = bitmap.asImageBitmap(),
                                contentDescription = "Microscope diffusion preview",
                                modifier = Modifier.fillMaxSize(),
                                contentScale = ContentScale.Fit,
                            )
                        }
                    }
                }
            }

            ElevatedCard(modifier = Modifier.fillMaxWidth()) {
                Column(
                    modifier = Modifier.padding(16.dp),
                    verticalArrangement = Arrangement.spacedBy(4.dp),
                ) {
                    Text("底部实时输出", style = MaterialTheme.typography.titleMedium)
                    if (recentEvents.isEmpty()) {
                        Text("等待真实 native trace…", style = MaterialTheme.typography.bodySmall)
                    } else {
                        recentEvents.forEach { event ->
                            val diffusion = if (event.diffusionStep > 0) {
                                " ${event.diffusionStep}/${event.diffusionTotal} t=${String.format(Locale.US, "%.1f", event.timestep)}"
                            } else {
                                ""
                            }
                            Text(
                                "+${event.elapsedMs}ms  ${event.phase}$diffusion  dur=${event.durationMs}ms  chunks=${event.chunkCount}",
                                style = MaterialTheme.typography.bodySmall,
                            )
                        }
                    }
                }
            }
            Spacer(modifier = Modifier.height(24.dp))
        }
    }

    @Composable
    fun PromptPage() {
'''
    text = replace_once(text, page_anchor, microscope_page, "microscope page")

    # Add a direct jump while generation is live, next to the real progress card.
    jump_anchor = '''                        Text(
                            "${(progress * 100).toInt()}%",
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                        intermediateBitmap?.let { bitmap ->
'''
    jump_new = '''                        Text(
                            "${(progress * 100).toInt()}%",
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                        TextButton(
                            onClick = {
                                coroutineScope.launch {
                                    pagerState.animateScrollToPage(3)
                                }
                            },
                        ) {
                            Text("打开显微镜")
                        }
                        intermediateBitmap?.let { bitmap ->
'''
    text = replace_once(text, jump_anchor, jump_new, "microscope jump action")

    tabs_old = '''                            val tabs = listOf(
                                stringResource(R.string.prompt_tab),
                                stringResource(R.string.result_tab),
                                stringResource(R.string.history_tab),
                            )
'''
    tabs_new = '''                            val tabs = listOf(
                                stringResource(R.string.prompt_tab),
                                stringResource(R.string.result_tab),
                                stringResource(R.string.history_tab),
                                "显微镜",
                            )
'''
    text = replace_once(text, tabs_old, tabs_new, "microscope tab")

    page_switch_anchor = '''                        2 -> ModelRunHistoryPage(
'''
    # Insert page 3 after the history call by replacing the end of the page switch
    # at the point immediately before the closing `}` of `when` is fragile; instead
    # transform the existing default page switch into an explicit branch by finding
    # the unique tail of the history invocation.
    history_tail = '''                            onBatchDelete = { showBatchDeleteDialog = true },
                        )
                    }
                }
'''
    history_tail_new = '''                            onBatchDelete = { showBatchDeleteDialog = true },
                        )

                        3 -> MicroscopePage()
                    }
                }
'''
    if page_switch_anchor not in text:
        raise RuntimeError("history page switch anchor missing")
    text = replace_once(text, history_tail, history_tail_new, "microscope pager branch")

    path.write_text(text, encoding="utf-8")


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: patch_h3.py <h2-patched-local-dream-root>", file=sys.stderr)
        return 2
    root = Path(sys.argv[1]).resolve()
    patch_gradle(root)
    patch_pipeline(root)
    patch_main_cpp(root)
    patch_service(root)
    patch_screen(root)
    print("S24U_IMAGE_HARNESS_H3_MICROSCOPE_PATCH_APPLIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
