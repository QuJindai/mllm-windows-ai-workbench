#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one literal match, found {count}")
    return text.replace(old, new, 1)


def patch_gradle(root: Path) -> None:
    p = root / "app/build.gradle.kts"
    text = p.read_text(encoding="utf-8")
    text = replace_once(text, "versionCode = 7410", "versionCode = 7411", "H6R5 versionCode")
    text = replace_once(text, 'versionName = "2.8.1-s24u-h6r4"', 'versionName = "2.8.1-s24u-h6r5"', "H6R5 versionName")
    p.write_text(text, encoding="utf-8")


def patch_pipeline(root: Path) -> None:
    p = root / "app/src/main/cpp/src/Pipeline.hpp"
    text = p.read_text(encoding="utf-8")

    # H6 required a batched [1,C,H,W] UNet prediction. Some QNN paths expose
    # the same prediction as [C,H,W]; scalar influence metrics still worked but
    # the preview silently returned an empty string. Accept both layouts.
    old = '''    if (chunk_pred.dimension() != 4 || fused_pred.dimension() != 4 ||
        chunk_pred.shape() != fused_pred.shape() || chunk_pred.shape()[0] < 1 ||
        chunk_pred.shape()[1] < 1)
      return "";
    xt::xarray<float> delta = xt::eval(xt::abs(chunk_pred - fused_pred));
    const int channels = static_cast<int>(delta.shape()[1]);
    const int h = static_cast<int>(delta.shape()[2]);
    const int w = static_cast<int>(delta.shape()[3]);
'''
    new = '''    const bool batched = chunk_pred.dimension() == 4 && fused_pred.dimension() == 4;
    const bool unbatched = chunk_pred.dimension() == 3 && fused_pred.dimension() == 3;
    if ((!batched && !unbatched) || chunk_pred.shape() != fused_pred.shape())
      return "";
    xt::xarray<float> delta = xt::eval(xt::abs(chunk_pred - fused_pred));
    const int channels = static_cast<int>(delta.shape()[batched ? 1 : 0]);
    const int h = static_cast<int>(delta.shape()[batched ? 2 : 1]);
    const int w = static_cast<int>(delta.shape()[batched ? 3 : 2]);
'''
    text = replace_once(text, old, new, "H6R5 influence layout support")
    text = replace_once(
        text,
        "        for (int c = 0; c < channels; ++c) value += delta(0, c, y, x);\n",
        "        for (int c = 0; c < channels; ++c)\n"
        "          value += batched ? delta(0, c, y, x) : delta(c, y, x);\n",
        "H6R5 influence indexing",
    )
    p.write_text(text, encoding="utf-8")


def patch_screen(root: Path) -> None:
    p = root / "app/src/main/java/io/github/xororz/localdream/ui/screens/ModelRunScreen.kt"
    text = p.read_text(encoding="utf-8")
    text = replace_once(text, "import java.io.File\n", "import java.io.File\nimport java.io.FileInputStream\nimport java.security.MessageDigest\n", "H6R5 hash imports")

    helper_anchor = '@SuppressLint("DefaultLocale")\n'
    helpers = '''private fun h6r5CachedSha256(context: Context, modelId: String, fileName: String): String {
    val file = File(File(context.filesDir, "models/$modelId"), fileName)
    if (!file.isFile || file.length() <= 0L) return "unavailable"
    val prefs = context.getSharedPreferences("h6r5_model_hashes", Context.MODE_PRIVATE)
    val cacheKey = "$modelId|$fileName|${file.length()}|${file.lastModified()}"
    prefs.getString(cacheKey, null)?.let { if (it.length == 64) return it }
    val digest = MessageDigest.getInstance("SHA-256")
    FileInputStream(file).use { input ->
        val buffer = ByteArray(8 * 1024 * 1024)
        while (true) {
            val read = input.read(buffer)
            if (read <= 0) break
            digest.update(buffer, 0, read)
        }
    }
    val value = digest.digest().joinToString("") { "%02x".format(it) }
    prefs.edit().putString(cacheKey, value).apply()
    return value
}

private fun h6r5ModelLoras(context: Context, modelId: String, isDmd2: Boolean): List<String> {
    val dir = File(context.filesDir, "models/$modelId")
    val files = dir.listFiles()?.asSequence()?.filter { it.isFile && it.name.startsWith("lora.") }
        ?.map { it.name }?.sorted()?.toList().orEmpty()
    return if (isDmd2 && files.none { it.contains("dmd2", ignoreCase = true) })
        listOf("DMD2 (merged)") + files else files
}

'''
    text = replace_once(text, helper_anchor, helpers + helper_anchor, "H6R5 model identity helpers")

    model_anchor = '''    LaunchedEffect(Unit) {
        if (!isRemote) {
            modelRepository.ensureLoaded()
        }
    }
'''
    model_state = '''    val h6r5ModelIsDmd2 = remember(model?.id, model?.name) {
        (model?.id?.contains("dmd2", ignoreCase = true) == true) ||
            (model?.name?.contains("dmd2", ignoreCase = true) == true)
    }
    val h6r5UnetSha256 by produceState(
        initialValue = if (isRemote) "remote-unavailable" else "pending",
        modelId, model?.id, isRemote,
    ) {
        value = if (isRemote) "remote-unavailable" else withContext(Dispatchers.IO) {
            h6r5CachedSha256(context, model?.id ?: modelId, "unet.bin")
        }
    }
    val h6r5ModelLoras by produceState(
        initialValue = emptyList<String>(), modelId, model?.id, h6r5ModelIsDmd2,
    ) {
        value = if (isRemote) emptyList() else withContext(Dispatchers.IO) {
            h6r5ModelLoras(context, model?.id ?: modelId, h6r5ModelIsDmd2)
        }
    }

'''
    text = replace_once(text, model_anchor, model_anchor + model_state, "H6R5 model identity state")

    payload_anchor = '            put("total_ms", microscope.totalMs)\n'
    payload = '''            put("model_id", model?.id ?: modelId)
            put("model_display_name", model?.name ?: modelId)
            put("model_backend_type", model?.backendType ?: "unknown")
            put("model_is_dmd2", h6r5ModelIsDmd2)
            put("model_loras", stringArrayJson(h6r5ModelLoras))
            put("scheduler_name", generationParams?.scheduler ?: scheduler)
            put("generation_seed", generationParams?.seed ?: returnedSeed ?: seed.toLongOrNull() ?: 0L)
            put("generation_steps", generationParams?.steps ?: steps.roundToInt())
            put("generation_cfg", (generationParams?.cfg ?: cfg).toDouble())
            put("unet_sha256", h6r5UnetSha256)
'''
    text = replace_once(text, payload_anchor, payload_anchor + payload, "H6R5 model identity WebView payload")
    text = replace_once(
        text,
        '            put("h6r3_marker", "S24U_H6R3_SEMANTIC_FIDELITY")\n',
        '            put("h6r3_marker", "S24U_H6R3_SEMANTIC_FIDELITY")\n'
        '            put("h6r5_marker", "S24U_H6R5_SEMANTIC_FIDELITY")\n',
        "H6R5 DEX marker",
    )
    p.write_text(text, encoding="utf-8")


def patch_js(root: Path) -> None:
    p = root / "app/src/main/assets/s24u_microscope/microscope.js"
    text = p.read_text(encoding="utf-8")
    helper = "  const cleanBpeText = (v) => txt(v,'').replaceAll('</w>',' ').replace(/\\s+/g,' ').trim();\n  function renderHumanReadableTokens(values){return arr(values).map(cleanBpeText).filter(Boolean).join(' ');}\n"
    text = replace_once(text, "  const clamp = (v,a,b) => Math.max(a,Math.min(b,v));\n", "  const clamp = (v,a,b) => Math.max(a,Math.min(b,v));\n" + helper, "H6R5 readable token helpers")

    # Human-facing chunk text must not expose BPE end-of-word markers.
    text = text.replace("txt(texts[i],'')", "cleanBpeText(texts[i])")
    text = replace_once(
        text,
        "    const pos=txt(arr(s.positive_chunks)[index],'(empty positive)');\n    const neg=txt(arr(s.negative_chunks)[index],'(empty negative)');\n",
        "    const pos=cleanBpeText(arr(s.positive_chunks)[index])||'(empty positive)';\n"
        "    const neg=cleanBpeText(arr(s.negative_chunks)[index])||'(empty negative)';\n",
        "H6R5 readable influence chunk text",
    )

    # Add model identity as a first-class runtime node after Time Accounting.
    identity_anchor = "      {name:'Prompt',backend:'App / CPU'"
    identity_node = "      {name:'MODEL IDENTITY',backend:txt(s.model_backend_type,'unknown'),shape:`${txt(s.model_display_name,txt(s.model_id))} · DMD2=${Boolean(s.model_is_dmd2)} · LoRA=[${arr(s.model_loras).join(', ')}] · scheduler=${txt(s.scheduler_name)} · seed=${txt(s.generation_seed)} · steps=${int(s.generation_steps)} · CFG=${num(s.generation_cfg).toFixed(3)} · unet SHA256=${txt(s.unet_sha256)}`,expected_calls:'—',observed_calls:'—',duration_ms:'—',execution_state:txt(s.model_id,'')?'captured':'waiting',input_source:'selected model + on-device model files + generation snapshot',output_destination:'reproducibility evidence'},\n"
    text = replace_once(text, identity_anchor, identity_node + identity_anchor, "H6R5 model identity runtime node")

    # Explicitly report image coverage instead of leaving a numeric sample with
    # a vague waiting placeholder.
    influence_anchor = "  function renderInfluence(s,force=false){\n    const samples=arr(s.influence_samples);"
    influence_new = "  function renderInfluence(s,force=false){\n    const samples=arr(s.influence_samples);const capturedImages=samples.filter(x=>Boolean(x.image_base64)).length;const influence_image_status=samples.length===0?'waiting':capturedImages===samples.length?'complete':capturedImages===0?'missing':'partial';const coverage=$('influence-coverage');if(coverage)coverage.textContent=`INFLUENCE IMAGE COVERAGE · ${capturedImages}/${samples.length} · ${influence_image_status.toUpperCase()}`;"
    text = replace_once(text, influence_anchor, influence_new, "H6R5 influence coverage")

    p.write_text(text, encoding="utf-8")


def patch_html(root: Path) -> None:
    p = root / "app/src/main/assets/s24u_microscope/index.html"
    text = p.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '        <div id="influence-metrics" class="metrics influence-metrics"></div>\n',
        '        <div id="influence-coverage" class="subtle">INFLUENCE IMAGE COVERAGE · 0/0 · WAITING</div>\n'
        '        <div id="influence-metrics" class="metrics influence-metrics"></div>\n',
        "H6R5 influence coverage HTML",
    )
    text = replace_once(text, '<details><summary>Token IDs</summary>', '<details><summary>RAW BPE / Token IDs</summary>', "H6R5 raw BPE fold label")
    p.write_text(text, encoding="utf-8")


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: patch_h6_v13_h6r5_truth_ui.py <h6r4-patched-root>", file=sys.stderr)
        return 2
    root = Path(sys.argv[1]).resolve()
    patch_gradle(root)
    patch_pipeline(root)
    patch_screen(root)
    patch_js(root)
    patch_html(root)
    print("S24U_IMAGE_HARNESS_H6R5_TRUTH_UI_APPLIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
