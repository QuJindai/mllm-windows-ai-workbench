#!/usr/bin/env python3
from pathlib import Path
import sys


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
        '''    data class MicroscopeEvent(
''',
        '''    data class DynamicsSample(
        val diffusionStep: Int = 0,
        val diffusionTotal: Int = 0,
        val timestep: Float = 0f,
        val deltaL2: Float = 0f,
        val deltaMeanAbs: Float = 0f,
        val latentCosine: Float = 0f,
        val latentMean: Float = 0f,
        val latentStd: Float = 0f,
        val unetMs: Long = 0L,
        val schedulerMs: Long = 0L,
        val imageBase64: String = "",
    )

    data class MicroscopeEvent(
''',
        'dynamics data class',
    )
    text = replace_once(
        text,
        '        val fusionWeights: List<Float> = emptyList(),\n    )\n\n    data class MicroscopeSnapshot(\n',
        '        val fusionWeights: List<Float> = emptyList(),\n'
        '        val latentDelta: Float = 0f,\n'
        '        val deltaL2: Float = 0f,\n'
        '        val deltaMeanAbs: Float = 0f,\n'
        '        val latentCosine: Float = 0f,\n'
        '        val latentMean: Float = 0f,\n'
        '        val latentStd: Float = 0f,\n'
        '        val dynamicsUnetMs: Long = 0L,\n'
        '        val dynamicsSchedulerMs: Long = 0L,\n'
        '    )\n\n    data class MicroscopeSnapshot(\n',
        'event dynamics fields',
    )
    text = replace_once(
        text,
        '        val influenceSamples: List<InfluenceSample> = emptyList(),\n    )\n',
        '        val influenceSamples: List<InfluenceSample> = emptyList(),\n'
        '        val dynamicsSamples: List<DynamicsSample> = emptyList(),\n'
        '    )\n',
        'snapshot dynamics history',
    )
    text = replace_once(
        text,
        '            fusionWeights = jsonFloatList(message, "fusion_weights"),\n        )\n',
        '            fusionWeights = jsonFloatList(message, "fusion_weights"),\n'
        '            latentDelta = message.optDouble("latent_delta", 0.0).toFloat(),\n'
        '            deltaL2 = message.optDouble("delta_l2", 0.0).toFloat(),\n'
        '            deltaMeanAbs = message.optDouble("delta_mean_abs", 0.0).toFloat(),\n'
        '            latentCosine = message.optDouble("latent_cosine", 0.0).toFloat(),\n'
        '            latentMean = message.optDouble("latent_mean", 0.0).toFloat(),\n'
        '            latentStd = message.optDouble("latent_std", 0.0).toFloat(),\n'
        '            dynamicsUnetMs = message.optLong("dynamics_unet_ms", 0L),\n'
        '            dynamicsSchedulerMs = message.optLong("dynamics_scheduler_ms", 0L),\n'
        '        )\n',
        'dynamics parser',
    )
    text = replace_once(
        text,
        '''        if (event.phase == "latent_map" && event.imageBase64.isNotBlank()) {
''',
        '''        if (event.phase == "latent_delta") {
            val dynamicsSample = DynamicsSample(
                diffusionStep = event.diffusionStep,
                diffusionTotal = event.diffusionTotal,
                timestep = event.timestep,
                deltaL2 = event.deltaL2,
                deltaMeanAbs = event.deltaMeanAbs,
                latentCosine = event.latentCosine,
                latentMean = event.latentMean,
                latentStd = event.latentStd,
                unetMs = event.dynamicsUnetMs,
                schedulerMs = event.dynamicsSchedulerMs,
                imageBase64 = event.imageBase64,
            )
            next = next.copy(
                dynamicsSamples = (next.dynamicsSamples + dynamicsSample).takeLast(8),
            )
        }
        if (event.phase == "latent_map" && event.imageBase64.isNotBlank()) {
''',
        'dynamics reducer',
    )
    path.write_text(text, encoding="utf-8")


def patch_screen(root: Path) -> None:
    path = root / "app/src/main/java/io/github/xororz/localdream/ui/screens/ModelRunScreen.kt"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '''        fun influenceJson(sample: BackgroundGenerationService.InfluenceSample): JSONObject = JSONObject().apply {
''',
        '''        fun dynamicsJson(sample: BackgroundGenerationService.DynamicsSample): JSONObject = JSONObject().apply {
            put("diffusion_step", sample.diffusionStep)
            put("diffusion_total", sample.diffusionTotal)
            put("timestep", sample.timestep.toDouble())
            put("delta_l2", sample.deltaL2.toDouble())
            put("delta_mean_abs", sample.deltaMeanAbs.toDouble())
            put("latent_cosine", sample.latentCosine.toDouble())
            put("latent_mean", sample.latentMean.toDouble())
            put("latent_std", sample.latentStd.toDouble())
            put("unet_ms", sample.unetMs)
            put("scheduler_ms", sample.schedulerMs)
            put("format", "jpeg")
            put("image_base64", sample.imageBase64)
        }

        fun influenceJson(sample: BackgroundGenerationService.InfluenceSample): JSONObject = JSONObject().apply {
''',
        'dynamics json helper',
    )
    text = replace_once(
        text,
        '''                        val mediaRevision = listOf(
                            microscope.processPreviews.lastOrNull()?.previewIndex ?: 0,
                            microscope.latentMaps.lastOrNull()?.diffusionStep ?: 0,
                            currentInfluenceRevision,
                        )
''',
        '''                        val mediaRevision = listOf(
                            microscope.processPreviews.lastOrNull()?.previewIndex ?: 0,
                            microscope.latentMaps.lastOrNull()?.diffusionStep ?: 0,
                            currentInfluenceRevision,
                            microscope.dynamicsSamples.lastOrNull()?.diffusionStep ?: 0,
                        )
''',
        'dynamics media revision',
    )
    text = replace_once(
        text,
        '''                        val previousInfluenceRevision =
                            (previousMediaRevision?.getOrNull(2) as? Int) ?: 0
''',
        '''                        val previousInfluenceRevision =
                            (previousMediaRevision?.getOrNull(2) as? Int) ?: 0
                        val previousDynamicsRevision =
                            (previousMediaRevision?.getOrNull(3) as? Int) ?: 0
''',
        'previous dynamics revision',
    )
    text = replace_once(
        text,
        '''                            val mediaReset = microscope.processPreviews.isEmpty() &&
                                microscope.latentMaps.isEmpty() && microscope.influenceSamples.isEmpty()
''',
        '''                            val mediaReset = microscope.processPreviews.isEmpty() &&
                                microscope.latentMaps.isEmpty() && microscope.influenceSamples.isEmpty() &&
                                microscope.dynamicsSamples.isEmpty()
''',
        'dynamics reset',
    )
    text = replace_once(
        text,
        '''                                    put("influence_samples", JSONArray().apply {
                                        microscope.influenceSamples.forEach { put(influenceJson(it)) }
                                    })
''',
        '''                                    put("influence_samples", JSONArray().apply {
                                        microscope.influenceSamples.forEach { put(influenceJson(it)) }
                                    })
                                    put("dynamics_samples", JSONArray().apply {
                                        microscope.dynamicsSamples.forEach { put(dynamicsJson(it)) }
                                    })
''',
        'dynamics bootstrap',
    )
    text = replace_once(
        text,
        '''                                val influenceDelta = microscope.influenceSamples.filter {
                                    it.diffusionStep * 100 + it.chunkIndex + 1 > previousInfluenceRevision
                                }
                                val mediaPayload = JSONObject().apply {
''',
        '''                                val influenceDelta = microscope.influenceSamples.filter {
                                    it.diffusionStep * 100 + it.chunkIndex + 1 > previousInfluenceRevision
                                }
                                val dynamicsDelta = microscope.dynamicsSamples.filter {
                                    it.diffusionStep > previousDynamicsRevision
                                }
                                val mediaPayload = JSONObject().apply {
''',
        'dynamics delta selection',
    )
    text = replace_once(
        text,
        '''                                    if (influenceDelta.isNotEmpty()) {
                                        put("influence_samples_delta", JSONArray().apply {
                                            influenceDelta.forEach { put(influenceJson(it)) }
                                        })
                                    }
''',
        '''                                    if (influenceDelta.isNotEmpty()) {
                                        put("influence_samples_delta", JSONArray().apply {
                                            influenceDelta.forEach { put(influenceJson(it)) }
                                        })
                                    }
                                    if (dynamicsDelta.isNotEmpty()) {
                                        put("dynamics_samples_delta", JSONArray().apply {
                                            dynamicsDelta.forEach { put(dynamicsJson(it)) }
                                        })
                                    }
''',
        'dynamics media delta',
    )
    path.write_text(text, encoding="utf-8")


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: patch_h6_v8_dynamics_android.py <h6r3-task3-root>", file=sys.stderr)
        return 2
    root = Path(sys.argv[1]).resolve()
    patch_service(root)
    patch_screen(root)
    print("S24U_IMAGE_HARNESS_H6R3_DYNAMICS_ANDROID_APPLIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
