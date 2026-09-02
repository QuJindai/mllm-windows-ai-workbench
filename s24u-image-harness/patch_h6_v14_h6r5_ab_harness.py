#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one literal match, found {count}")
    return text.replace(old, new, 1)


def patch_screen(root: Path) -> None:
    p = root / "app/src/main/java/io/github/xororz/localdream/ui/screens/ModelRunScreen.kt"
    text = p.read_text(encoding="utf-8")
    text = replace_once(text, "import java.nio.ByteBuffer\n" if "import java.nio.ByteBuffer\n" in text else "import java.security.MessageDigest\n",
                        "import java.nio.ByteBuffer\nimport java.security.MessageDigest\n" if "import java.nio.ByteBuffer\n" not in text else "import java.nio.ByteBuffer\n",
                        "H6R5 experiment hash import")

    helper_anchor = '@SuppressLint("DefaultLocale")\n'
    helpers = '''private data class H6R5ExperimentResult(
    val experimentId: String,
    val variant: String,
    val seed: Long,
    val steps: Int,
    val resultSha256: String,
    val bitmap: Bitmap,
)

private fun h6r5BitmapSha256(bitmap: Bitmap): String {
    val buffer = ByteBuffer.allocate(bitmap.byteCount)
    bitmap.copyPixelsToBuffer(buffer)
    return MessageDigest.getInstance("SHA-256").digest(buffer.array())
        .joinToString("") { "%02x".format(it) }
}

'''
    text = replace_once(text, helper_anchor, helpers + helper_anchor, "H6R5 experiment result helpers")

    state_anchor = '    var batchGenerationJob: Job? by remember { mutableStateOf(null) }\n'
    states = '''    var h6r5ExperimentResults by remember { mutableStateOf<List<H6R5ExperimentResult>>(emptyList()) }
    var h6r5ActiveExperimentId by remember { mutableStateOf<String?>(null) }
    var h6r5ActiveExperimentVariant by remember { mutableStateOf<String?>(null) }
    var h6r5ActiveExperimentSeed by remember { mutableStateOf<Long?>(null) }
    var h6r5LastResultSha256 by remember { mutableStateOf("") }
    var h6r5ExperimentRunning by remember { mutableStateOf(false) }
'''
    text = replace_once(text, state_anchor, state_anchor + states, "H6R5 experiment state")

    result_anchor = '''                    currentBitmap = state.bitmap
                    generationParams = newParams
'''
    result_capture = '''                    h6r5LastResultSha256 = h6r5BitmapSha256(state.bitmap)
                    val experiment_id = h6r5ActiveExperimentId
                    val experimentVariant = h6r5ActiveExperimentVariant
                    val experimentSeed = h6r5ActiveExperimentSeed
                    if (experiment_id != null && experimentVariant != null && experimentSeed != null) {
                        h6r5ExperimentResults = (h6r5ExperimentResults + H6R5ExperimentResult(
                            experimentId = experiment_id,
                            variant = experimentVariant,
                            seed = experimentSeed,
                            steps = generationParamsTmp.steps,
                            resultSha256 = h6r5LastResultSha256,
                            bitmap = state.bitmap,
                        )).takeLast(8)
                    }
                    currentBitmap = state.bitmap
                    generationParams = newParams
'''
    text = replace_once(text, result_anchor, result_capture, "H6R5 experiment result capture")

    page_anchor = '    // === Page Composable Functions ===\n'
    runner = '''    fun startH6R5Experiment(kind: String, variants: List<Pair<String, Int>>) {
        if (isRunning || h6r5ExperimentRunning || variants.isEmpty()) return
        focusManager.clearFocus()
        val sameSeed = seed.toLongOrNull() ?: (System.currentTimeMillis() and 0x7fffffffL)
        val experimentId = "${kind}-${System.currentTimeMillis()}"
        val originalFusion = fusionMode
        val originalSteps = steps
        h6r5ExperimentResults = emptyList()
        h6r5ActiveExperimentId = experimentId
        h6r5ActiveExperimentSeed = sameSeed
        h6r5ExperimentRunning = true
        isRunning = true
        batchGenerationJob = coroutineScope.launch {
            try {
                variants.forEachIndexed { index, (variantFusion, variantSteps) ->
                    // A terminal GenerationState from the previous variant sets the
                    // ordinary isRunning flag false. Restore it for the next variant;
                    // the separate experiment guard remains true for the whole session.
                    isRunning = true
                    currentBatchIndex = index + 1
                    fusionMode = variantFusion
                    steps = variantSteps.toFloat()
                    h6r5ActiveExperimentVariant = if (kind == "fusion") variantFusion else "${variantSteps}_steps"
                    generationParamsTmp = GenerationParameters(
                        steps = variantSteps,
                        cfg = cfg,
                        seed = sameSeed,
                        prompt = promptField.text,
                        negativePrompt = negativePromptField.text,
                        generationTime = "",
                        width = currentWidth,
                        height = currentHeight,
                        runOnCpu = model?.runOnCpu ?: false,
                        denoiseStrength = denoiseStrength,
                        useOpenCL = useOpenCL,
                        scheduler = scheduler,
                    )
                    val experimentIntent = Intent(context, BackgroundGenerationService::class.java).apply {
                        putExtra("prompt", promptField.text)
                        putExtra("negative_prompt", negativePromptField.text)
                        putExtra("steps", variantSteps)
                        putExtra("cfg", cfg)
                        putExtra("fusion_mode", variantFusion)
                        putExtra("fusion_alpha", fusionAlpha)
                        putExtra("seed", sameSeed)
                        putExtra("width", currentWidth)
                        putExtra("height", currentHeight)
                        putExtra("effective_width", effectiveWidth)
                        putExtra("effective_height", effectiveHeight)
                        putExtra("denoise_strength", denoiseStrength)
                        putExtra("use_opencl", useOpenCL)
                        putExtra("scheduler", scheduler)
                        putExtra("aspect_ratio", aspectRatio)
                        putExtra("backend_host", backendHost)
                        putExtra("experiment_id", experimentId)
                        putExtra("experiment_variant", h6r5ActiveExperimentVariant)
                        if (selectedImageUri != null && base64EncodeDone) {
                            putExtra("has_image", true)
                            if (isInpaintMode && maskBitmap != null) putExtra("has_mask", true)
                        }
                    }
                    context.startForegroundService(experimentIntent)
                    val terminal = BackgroundGenerationService.generationState.first { state ->
                        state is GenerationState.Complete || state is GenerationState.Error
                    }
                    withTimeoutOrNull(5000L) {
                        BackgroundGenerationService.isServiceRunning.first { !it }
                    }
                    if (terminal is GenerationState.Error) return@launch
                    BackgroundGenerationService.resetState()
                }
            } finally {
                fusionMode = originalFusion
                steps = originalSteps
                h6r5ActiveExperimentId = null
                h6r5ActiveExperimentVariant = null
                h6r5ActiveExperimentSeed = null
                currentBatchIndex = 0
                h6r5ExperimentRunning = false
                isRunning = false
            }
        }
    }

'''
    text = replace_once(text, page_anchor, runner + page_anchor, "H6R5 experiment runner")

    generate_anchor = '''                        Button(
                            onClick = {
                                focusManager.clearFocus()
'''
    experiment_ui = '''                        Text(
                            text = "SEMANTIC A/B · same seed",
                            style = MaterialTheme.typography.labelMedium,
                            fontWeight = FontWeight.Bold,
                        )
                        Row(
                            modifier = Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
                            horizontalArrangement = Arrangement.spacedBy(8.dp),
                        ) {
                            OutlinedButton(
                                onClick = {
                                    startH6R5Experiment(
                                        "fusion",
                                        listOf(
                                            "first_only" to steps.roundToInt(),
                                            "equal_mean" to steps.roundToInt(),
                                            "token_weighted" to steps.roundToInt(),
                                            "anchor_residual" to steps.roundToInt(),
                                        ),
                                    )
                                },
                                enabled = !isRunning && !h6r5ExperimentRunning,
                            ) { Text("4 Fusion · same seed") }
                            OutlinedButton(
                                onClick = {
                                    startH6R5Experiment(
                                        "steps",
                                        listOf(fusionMode to 8, fusionMode to 16, fusionMode to 24),
                                    )
                                },
                                enabled = !isRunning && !h6r5ExperimentRunning,
                            ) { Text("8 / 16 / 24 · same seed") }
                        }
                        if (h6r5ExperimentResults.isNotEmpty()) {
                            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                                Text(
                                    "A/B RESULTS · experiment_id=${h6r5ExperimentResults.last().experimentId}",
                                    style = MaterialTheme.typography.labelSmall,
                                )
                                Row(
                                    modifier = Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
                                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                                ) {
                                    h6r5ExperimentResults.forEach { result ->
                                        Column(modifier = Modifier.width(144.dp)) {
                                            Image(
                                                bitmap = result.bitmap.asImageBitmap(),
                                                contentDescription = result.variant,
                                                modifier = Modifier.size(140.dp),
                                                contentScale = ContentScale.Crop,
                                            )
                                            Text(result.variant, fontWeight = FontWeight.Bold)
                                            Text("seed=${result.seed} · steps=${result.steps}", style = MaterialTheme.typography.labelSmall)
                                            Text("result_sha256=${result.resultSha256.take(12)}…", style = MaterialTheme.typography.labelSmall)
                                        }
                                    }
                                }
                            }
                        }

'''
    text = replace_once(text, generate_anchor, experiment_ui + generate_anchor, "H6R5 experiment UI")

    # Ordinary generation must also stay disabled for the full A/B session even
    # though each individual Complete state temporarily clears isRunning.
    text = replace_once(
        text,
        '''                            enabled = serviceState !is GenerationState.Progress &&
                                !isRunning && !isUpscaling && !isUltrafixPreparing,
''',
        '''                            enabled = serviceState !is GenerationState.Progress &&
                                !isRunning && !h6r5ExperimentRunning && !isUpscaling && !isUltrafixPreparing,
''',
        "H6R5 ordinary generate guard",
    )

    payload_anchor = '            put("unet_sha256", h6r5UnetSha256)\n'
    payload = '''            put("experiment_id", h6r5ActiveExperimentId ?: h6r5ExperimentResults.lastOrNull()?.experimentId.orEmpty())
            put("result_sha256", h6r5LastResultSha256)
'''
    text = replace_once(text, payload_anchor, payload_anchor + payload, "H6R5 experiment WebView evidence")
    p.write_text(text, encoding="utf-8")


def patch_js(root: Path) -> None:
    p = root / "app/src/main/assets/s24u_microscope/microscope.js"
    text = p.read_text(encoding="utf-8")
    old = " · unet SHA256=${txt(s.unet_sha256)}`"
    new = " · unet SHA256=${txt(s.unet_sha256)} · SEMANTIC A/B experiment_id=${txt(s.experiment_id,'none')} · result_sha256=${txt(s.result_sha256,'pending')}`"
    text = replace_once(text, old, new, "H6R5 experiment runtime evidence")
    p.write_text(text, encoding="utf-8")


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: patch_h6_v14_h6r5_ab_harness.py <h6r5-v13-root>", file=sys.stderr)
        return 2
    root = Path(sys.argv[1]).resolve()
    patch_screen(root)
    patch_js(root)
    print("S24U_IMAGE_HARNESS_H6R5_AB_HARNESS_APPLIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
