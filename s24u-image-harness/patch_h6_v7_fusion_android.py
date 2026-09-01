#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one literal match, found {count}")
    return text.replace(old, new, 1)


def patch_service(root: Path) -> None:
    path = root / "app/src/main/java/io/github/xororz/localdream/service/BackgroundGenerationService.kt"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '        val negativeEffectiveWeight: Float = 0f,\n    )\n\n    data class MicroscopeSnapshot(\n',
        '        val negativeEffectiveWeight: Float = 0f,\n'
        '        val fusionMode: String = "equal_mean",\n'
        '        val fusionAlpha: Float = 0.5f,\n'
        '        val fusionWeights: List<Float> = emptyList(),\n'
        '    )\n\n    data class MicroscopeSnapshot(\n',
        "event fusion fields",
    )
    text = replace_once(
        text,
        '        val negativeEffectiveWeight: Float = 0f,\n        val processPreviews: List<MicroscopePreview> = emptyList(),\n',
        '        val negativeEffectiveWeight: Float = 0f,\n'
        '        val fusionMode: String = "equal_mean",\n'
        '        val fusionAlpha: Float = 0.5f,\n'
        '        val fusionWeights: List<Float> = emptyList(),\n'
        '        val processPreviews: List<MicroscopePreview> = emptyList(),\n',
        "snapshot fusion fields",
    )
    text = replace_once(
        text,
        '        val cfg = intent.getFloatExtra("cfg", 7f)\n        val seed = if (intent.hasExtra("seed")) intent.getLongExtra("seed", 0) else null\n',
        '        val cfg = intent.getFloatExtra("cfg", 7f)\n'
        '        val fusionMode = intent.getStringExtra("fusion_mode") ?: "equal_mean"\n'
        '        val fusionAlpha = intent.getFloatExtra("fusion_alpha", 0.5f).coerceIn(0f, 1f)\n'
        '        val seed = if (intent.hasExtra("seed")) intent.getLongExtra("seed", 0) else null\n',
        "service fusion extras",
    )
    text = replace_once(
        text,
        '        Log.d("GenerationService", "params: steps=$steps, cfg=$cfg, seed=$seed")\n',
        '        Log.d("GenerationService", "params: steps=$steps, cfg=$cfg, fusion=$fusionMode, alpha=$fusionAlpha, seed=$seed")\n',
        "fusion log",
    )
    text = replace_once(
        text,
        '''                cfg,
                seed,
''',
        '''                cfg,
                fusionMode,
                fusionAlpha,
                seed,
''',
        "fusion run args",
    )
    text = replace_once(
        text,
        '''        cfg: Float,
        seed: Long?,
''',
        '''        cfg: Float,
        fusionMode: String,
        fusionAlpha: Float,
        seed: Long?,
''',
        "fusion signature",
    )
    text = replace_once(
        text,
        '                put("cfg", cfg)\n                // Per-step previews come back as base64 JPEG (tiny) instead of\n',
        '                put("cfg", cfg)\n'
        '                put("fusion_mode", fusionMode)\n'
        '                put("fusion_alpha", fusionAlpha.toDouble())\n'
        '                // Per-step previews come back as base64 JPEG (tiny) instead of\n',
        "HTTP fusion fields",
    )
    text = replace_once(
        text,
        '''    private fun jsonStringList(message: JSONObject, key: String): List<String> {
        val array = message.optJSONArray(key) ?: return emptyList()
        return List(array.length()) { index -> array.optString(index) }
    }

    private fun appendMicroscopeTrace(message: JSONObject) {
''',
        '''    private fun jsonStringList(message: JSONObject, key: String): List<String> {
        val array = message.optJSONArray(key) ?: return emptyList()
        return List(array.length()) { index -> array.optString(index) }
    }

    private fun jsonFloatList(message: JSONObject, key: String): List<Float> {
        val array = message.optJSONArray(key) ?: return emptyList()
        return List(array.length()) { index -> array.optDouble(index, 0.0).toFloat() }
    }

    private fun appendMicroscopeTrace(message: JSONObject) {
''',
        "json float list",
    )
    text = replace_once(
        text,
        '''            negativeEffectiveWeight = message.optDouble("negative_effective_weight", 0.0).toFloat(),
        )
''',
        '''            negativeEffectiveWeight = message.optDouble("negative_effective_weight", 0.0).toFloat(),
            fusionMode = message.optString("fusion_mode", "equal_mean"),
            fusionAlpha = message.optDouble("fusion_alpha", 0.5).toFloat(),
            fusionWeights = jsonFloatList(message, "fusion_weights"),
        )
''',
        "fusion event parser",
    )
    text = replace_once(
        text,
        '''            negativeEffectiveWeight = if (event.phase == "unet_step") event.negativeEffectiveWeight else previous.negativeEffectiveWeight,
            latentWidth = if (event.latentWidth > 0) event.latentWidth else previous.latentWidth,
''',
        '''            negativeEffectiveWeight = if (event.phase == "unet_step") event.negativeEffectiveWeight else previous.negativeEffectiveWeight,
            fusionMode = if (event.phase == "unet_step") event.fusionMode else previous.fusionMode,
            fusionAlpha = if (event.phase == "unet_step") event.fusionAlpha else previous.fusionAlpha,
            fusionWeights = if (event.phase == "unet_step") event.fusionWeights else previous.fusionWeights,
            latentWidth = if (event.latentWidth > 0) event.latentWidth else previous.latentWidth,
''',
        "fusion reducer",
    )
    path.write_text(text, encoding="utf-8")


def patch_screen(root: Path) -> None:
    path = root / "app/src/main/java/io/github/xororz/localdream/ui/screens/ModelRunScreen.kt"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '    var cfg by remember { mutableFloatStateOf(GenerationDefaults.GLOBAL.cfg) }\n    var steps by remember { mutableFloatStateOf(GenerationDefaults.GLOBAL.steps) }\n',
        '    var cfg by remember { mutableFloatStateOf(GenerationDefaults.GLOBAL.cfg) }\n'
        '    var fusionMode by remember { mutableStateOf("equal_mean") }\n'
        '    var fusionAlpha by remember { mutableFloatStateOf(0.5f) }\n'
        '    var steps by remember { mutableFloatStateOf(GenerationDefaults.GLOBAL.steps) }\n',
        "fusion UI state",
    )

    if text.count('                    putExtra("cfg", cfg)\n') != 2:
        raise RuntimeError("fusion intent anchor expected exactly two cfg extras")
    text = text.replace(
        '                    putExtra("cfg", cfg)\n',
        '                    putExtra("cfg", cfg)\n'
        '                    putExtra("fusion_mode", fusionMode)\n'
        '                    putExtra("fusion_alpha", fusionAlpha)\n',
    )

    text = text.replace('.coerceIn(1, 4)', '.coerceIn(1, 8)', 2)
    text = replace_once(
        text,
        '''                                Text(
                                    text = "POS CHUNKS → $positiveChunks × fixed-77 CLIP · NEG CHUNKS → $negativeChunks",
                                    style = MaterialTheme.typography.labelSmall,
                                )
''',
        '''                                Text(
                                    text = "POS CHUNKS → $positiveChunks × fixed-77 CLIP · NEG CHUNKS → $negativeChunks",
                                    style = MaterialTheme.typography.labelSmall,
                                )
                                Text(
                                    text = "SEMANTIC FIDELITY LAB · FUSION",
                                    style = MaterialTheme.typography.labelMedium,
                                    fontWeight = FontWeight.Bold,
                                )
                                Row(
                                    modifier = Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
                                    horizontalArrangement = Arrangement.spacedBy(4.dp),
                                ) {
                                    listOf(
                                        "equal_mean" to "Equal Mean",
                                        "first_only" to "First Only",
                                        "token_weighted" to "Token Weighted",
                                        "anchor_residual" to "Anchor + Residual",
                                    ).forEach { (mode, label) ->
                                        TextButton(onClick = { fusionMode = mode }) {
                                            Text(if (fusionMode == mode) "● $label" else label)
                                        }
                                    }
                                }
                                if (fusionMode == "anchor_residual") {
                                    Slider(
                                        value = fusionAlpha,
                                        onValueChange = { fusionAlpha = it.coerceIn(0f, 1f) },
                                        valueRange = 0f..1f,
                                        steps = 9,
                                    )
                                    Text(
                                        text = "Anchor residual α → $fusionAlpha",
                                        style = MaterialTheme.typography.labelSmall,
                                    )
                                }
                                Text(
                                    text = "默认 Equal Mean；实验融合只有显式选择时启用。",
                                    style = MaterialTheme.typography.labelSmall,
                                )
''',
        "fusion selector card",
    )
    text = replace_once(
        text,
        '''        fun stringArrayJson(values: List<String>): JSONArray = JSONArray().apply {
            values.forEach { put(it) }
        }
''',
        '''        fun stringArrayJson(values: List<String>): JSONArray = JSONArray().apply {
            values.forEach { put(it) }
        }

        fun floatArrayJson(values: List<Float>): JSONArray = JSONArray().apply {
            values.forEach { put(it.toDouble()) }
        }
''',
        "float JSON helper",
    )
    text = replace_once(
        text,
        '            put("negative_effective_weight", microscope.negativeEffectiveWeight.toDouble())\n            put("scheduler_seen", microscope.schedulerSeen)\n',
        '            put("negative_effective_weight", microscope.negativeEffectiveWeight.toDouble())\n'
        '            put("fusion_mode", microscope.fusionMode)\n'
        '            put("fusion_alpha", microscope.fusionAlpha.toDouble())\n'
        '            put("fusion_weights", floatArrayJson(microscope.fusionWeights))\n'
        '            put("scheduler_seen", microscope.schedulerSeen)\n',
        "fusion WebView payload",
    )
    path.write_text(text, encoding="utf-8")


def patch_js(root: Path) -> None:
    path = root / "app/src/main/assets/s24u_microscope/microscope.js"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '''    const k=Math.max(arr(s.positive_chunk_tokens).length,arr(s.negative_chunk_tokens).length,1),hidden=int(s.hidden_dim),step=int(s.diffusion_step),total=int(s.diffusion_total),cfg=num(s.cfg_value,num(s.cfg,1));
    const posWeight=num(s.positive_effective_weight,cfg),negWeight=num(s.negative_effective_weight,Math.max(cfg-1,0)),negEncoded=Boolean(s.negative_encoded);
    const negTruth=negEncoded&&negWeight===0?'NEG effective=0 · 已编码，但本轮不参与最终 guidance':`NEG effective=${negWeight.toFixed(3)} · ${negEncoded?'已编码':'无用户 Negative 输入'}`;
''',
        '''    const k=Math.max(arr(s.positive_chunk_tokens).length,arr(s.negative_chunk_tokens).length,1),hidden=int(s.hidden_dim),step=int(s.diffusion_step),total=int(s.diffusion_total),cfg=num(s.cfg_value,num(s.cfg,1));
    const posWeight=num(s.positive_effective_weight,cfg),negWeight=num(s.negative_effective_weight,Math.max(cfg-1,0)),negEncoded=Boolean(s.negative_encoded);
    const negTruth=negEncoded&&negWeight===0?'NEG effective=0 · 已编码，但本轮不参与最终 guidance':`NEG effective=${negWeight.toFixed(3)} · ${negEncoded?'已编码':'无用户 Negative 输入'}`;
    const fusionMode=txt(s.fusion_mode,'equal_mean'),fusionAlpha=num(s.fusion_alpha,0.5),fusionWeights=arr(s.fusion_weights).map(num);
    const fusionWeightText=fusionWeights.length?`[${fusionWeights.map(v=>v.toFixed(3)).join(', ')}]`:'—';
''',
        "fusion JS state",
    )
    text = replace_once(
        text,
        "      formula('ε̄ₜ = (1/K) Σₖ εₜ⁽ᵏ⁾',`step ${step}/${total||'—'} · K=${k}`,'当前默认仍是多 chunk prediction 等权均值；H6R3 诊断阶段暂不改变。'),\n",
        "      formula('FUSION LAB · ε̄ₜ = Fuse(εₜ⁽¹…K⁾)',`mode=${fusionMode} · α=${fusionAlpha.toFixed(2)} · weights=${fusionWeightText}`,'默认 equal_mean 保持 H2 基线；first_only / token_weighted / anchor_residual 只有显式选择才启用。'),\n",
        "fusion lab formula",
    )
    path.write_text(text, encoding="utf-8")


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: patch_h6_v7_fusion_android.py <h6r3-task2-root>", file=sys.stderr)
        return 2
    root = Path(sys.argv[1]).resolve()
    patch_service(root)
    patch_screen(root)
    patch_js(root)
    print("S24U_IMAGE_HARNESS_H6R3_FUSION_ANDROID_APPLIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
