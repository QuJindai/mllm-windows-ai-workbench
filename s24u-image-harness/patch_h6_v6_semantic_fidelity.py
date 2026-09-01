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
    path = root / "app/build.gradle.kts"
    text = path.read_text(encoding="utf-8")
    text = replace_once(text, "versionCode = 7408", "versionCode = 7409", "H6R3 versionCode")
    text = replace_once(
        text,
        'versionName = "2.8.1-s24u-h6r2"',
        'versionName = "2.8.1-s24u-h6r3"',
        "H6R3 versionName",
    )
    path.write_text(text, encoding="utf-8")


def patch_pipeline(root: Path) -> None:
    path = root / "app/src/main/cpp/src/Pipeline.hpp"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "  float influence_delta_l2 = 0.0f;\n};\n",
        "  float influence_delta_l2 = 0.0f;\n"
        "  float cfg_value = 1.0f;\n"
        "  bool negative_encoded = false;\n"
        "  float positive_effective_weight = 1.0f;\n"
        "  float negative_effective_weight = 0.0f;\n"
        "};\n",
        "H6R3 guidance trace fields",
    )
    text = replace_once(
        text,
        "      const bool skip_uncond = canSkipUncond() && (req.cfg == 1.0f);\n\n"
        "      std::vector<xt::xarray<float>> chunk_predictions;\n",
        "      const bool skip_uncond = canSkipUncond() && (req.cfg == 1.0f);\n"
        "      const bool negative_encoded = !req.negative_prompt.empty();\n"
        "      const float positive_effective_weight = req.cfg;\n"
        "      const float negative_effective_weight =\n"
        "          skip_uncond ? 0.0f : std::max(req.cfg - 1.0f, 0.0f);\n\n"
        "      std::vector<xt::xarray<float>> chunk_predictions;\n",
        "H6R3 guidance semantics computation",
    )
    text = replace_once(
        text,
        "      unet_trace.hidden_dim = cond.hidden_dim;\n"
        "      emit_trace(unet_trace);\n",
        "      unet_trace.hidden_dim = cond.hidden_dim;\n"
        "      unet_trace.cfg_value = req.cfg;\n"
        "      unet_trace.negative_encoded = negative_encoded;\n"
        "      unet_trace.positive_effective_weight = positive_effective_weight;\n"
        "      unet_trace.negative_effective_weight = negative_effective_weight;\n"
        "      emit_trace(unet_trace);\n",
        "H6R3 UNet guidance trace",
    )
    path.write_text(text, encoding="utf-8")


def patch_main_cpp(root: Path) -> None:
    path = root / "app/src/main/cpp/src/main.cpp"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '''                        {"influence_delta_l2", trace.influence_delta_l2},
                        {"image_base64", trace.image_base64}};
''',
        '''                        {"influence_delta_l2", trace.influence_delta_l2},
                        {"cfg_value", trace.cfg_value},
                        {"negative_encoded", trace.negative_encoded},
                        {"positive_effective_weight", trace.positive_effective_weight},
                        {"negative_effective_weight", trace.negative_effective_weight},
                        {"image_base64", trace.image_base64}};
''',
        "H6R3 guidance SSE serialization",
    )
    path.write_text(text, encoding="utf-8")


def patch_service(root: Path) -> None:
    path = root / "app/src/main/java/io/github/xororz/localdream/service/BackgroundGenerationService.kt"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '''        val influenceFusedCosine: Float = 0f,
        val influenceDeltaL2: Float = 0f,
    )

    data class MicroscopeSnapshot(
''',
        '''        val influenceFusedCosine: Float = 0f,
        val influenceDeltaL2: Float = 0f,
        val cfgValue: Float = 1f,
        val negativeEncoded: Boolean = false,
        val positiveEffectiveWeight: Float = 1f,
        val negativeEffectiveWeight: Float = 0f,
    )

    data class MicroscopeSnapshot(
''',
        "H6R3 event guidance fields",
    )
    text = replace_once(
        text,
        '''        val maxChunks: Int = 8,
        val processPreviews: List<MicroscopePreview> = emptyList(),
''',
        '''        val maxChunks: Int = 8,
        val cfgValue: Float = 1f,
        val negativeEncoded: Boolean = false,
        val positiveEffectiveWeight: Float = 1f,
        val negativeEffectiveWeight: Float = 0f,
        val processPreviews: List<MicroscopePreview> = emptyList(),
''',
        "H6R3 snapshot guidance fields",
    )
    text = replace_once(
        text,
        '''            influenceFusedCosine = message.optDouble("influence_fused_cosine", 0.0).toFloat(),
            influenceDeltaL2 = message.optDouble("influence_delta_l2", 0.0).toFloat(),
        )
''',
        '''            influenceFusedCosine = message.optDouble("influence_fused_cosine", 0.0).toFloat(),
            influenceDeltaL2 = message.optDouble("influence_delta_l2", 0.0).toFloat(),
            cfgValue = message.optDouble("cfg_value", 1.0).toFloat(),
            negativeEncoded = message.optBoolean("negative_encoded", false),
            positiveEffectiveWeight = message.optDouble("positive_effective_weight", 1.0).toFloat(),
            negativeEffectiveWeight = message.optDouble("negative_effective_weight", 0.0).toFloat(),
        )
''',
        "H6R3 guidance parser",
    )
    text = replace_once(
        text,
        '''            skipUncond = if (event.phase == "unet_step") event.skipUncond else previous.skipUncond,
            latentWidth = if (event.latentWidth > 0) event.latentWidth else previous.latentWidth,
''',
        '''            skipUncond = if (event.phase == "unet_step") event.skipUncond else previous.skipUncond,
            cfgValue = if (event.phase == "unet_step") event.cfgValue else previous.cfgValue,
            negativeEncoded = if (event.phase == "unet_step") event.negativeEncoded else previous.negativeEncoded,
            positiveEffectiveWeight = if (event.phase == "unet_step") event.positiveEffectiveWeight else previous.positiveEffectiveWeight,
            negativeEffectiveWeight = if (event.phase == "unet_step") event.negativeEffectiveWeight else previous.negativeEffectiveWeight,
            latentWidth = if (event.latentWidth > 0) event.latentWidth else previous.latentWidth,
''',
        "H6R3 guidance reducer",
    )
    path.write_text(text, encoding="utf-8")


def patch_screen(root: Path) -> None:
    path = root / "app/src/main/java/io/github/xororz/localdream/ui/screens/ModelRunScreen.kt"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '            put("h6r2_marker", "S24U_H6R2_OBSERVABILITY_FALLBACK")\n',
        '            put("h6r2_marker", "S24U_H6R2_OBSERVABILITY_FALLBACK")\n'
        '            put("h6r3_marker", "S24U_H6R3_SEMANTIC_FIDELITY")\n',
        "H6R3 DEX marker",
    )
    text = replace_once(
        text,
        '            put("skip_uncond", microscope.skipUncond)\n',
        '            put("skip_uncond", microscope.skipUncond)\n'
        '            put("cfg_value", microscope.cfgValue.toDouble())\n'
        '            put("negative_encoded", microscope.negativeEncoded)\n'
        '            put("positive_effective_weight", microscope.positiveEffectiveWeight.toDouble())\n'
        '            put("negative_effective_weight", microscope.negativeEffectiveWeight.toDouble())\n',
        "H6R3 guidance WebView payload",
    )
    path.write_text(text, encoding="utf-8")


def patch_js(root: Path) -> None:
    path = root / "app/src/main/assets/s24u_microscope/microscope.js"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "      metric('Negative 输入 / 参与',`${int(s.negative_input_tokens)} / ${int(s.negative_effective_tokens)}`),",
        "      metric('Negative token 输入 / 编码',`${int(s.negative_input_tokens)} / ${int(s.negative_effective_tokens)}`),",
        "H6R3 negative token wording",
    )
    old = '''  function renderMechanism(s){const k=Math.max(arr(s.positive_chunk_tokens).length,arr(s.negative_chunk_tokens).length,1),hidden=int(s.hidden_dim),step=int(s.diffusion_step),total=int(s.diffusion_total),cfg=num(s.cfg,1);$('formula-list').replaceChildren(
    formula('K = min(Kmax, ceil(Ncontent / 75))',`Ncontent=${int(s.positive_input_tokens)}, K=${k}`, '每块固定 77 slots，其中最多 75 个内容 token。'),
    formula('Cₖ = CLIP(Tₖ),  Cₖ ∈ R^(77×hidden)',`77 × ${hidden||'hidden'} · K=${k}`,'每个 chunk 独立形成条件向量。'),
    formula('ε̄ₜ = (1/K) Σₖ εₜ⁽ᵏ⁾',`step ${step}/${total||'—'} · CFG=${cfg}`,'多 chunk 的真实 UNet 预测在 native 层取均值。'),
    formula('Iₖ = |εₜ⁽ᵏ⁾ − ε̄ₜ|',`H6 influence samples=${arr(s.influence_samples).length}`,'H6 展示的是 chunk prediction 相对 fused prediction 的差异，不是 cross-attention。'),
    formula('zₜ₋₁ = Scheduler(zₜ, ε̄ₜ, t)',`t=${num(s.timestep).toFixed(2)} · seen=${Boolean(s.scheduler_seen)}`,'Scheduler 使用的 ε̄ₜ 与 H2 完全相同。')
  );
    const grid=$('tensor-grid');grid.replaceChildren();[['CLIP seq',int(s.seq_len)||'—'],['Hidden',hidden||'—'],['Latent',int(s.latent_width)?`${int(s.latent_width)}×${int(s.latent_height)}`:'—'],['Chunks',k],['Influence',arr(s.influence_samples).length],['Scheduler',s.scheduler_seen?'YES':'NO']].forEach(([a,b])=>{const d=document.createElement('div');d.className='tensor-item';d.innerHTML='<span></span><strong></strong>';d.children[0].textContent=a;d.children[1].textContent=String(b);grid.appendChild(d);});
  }
'''
    new = '''  function renderMechanism(s){
    const k=Math.max(arr(s.positive_chunk_tokens).length,arr(s.negative_chunk_tokens).length,1),hidden=int(s.hidden_dim),step=int(s.diffusion_step),total=int(s.diffusion_total),cfg=num(s.cfg_value,num(s.cfg,1));
    const posWeight=num(s.positive_effective_weight,cfg),negWeight=num(s.negative_effective_weight,Math.max(cfg-1,0)),negEncoded=Boolean(s.negative_encoded);
    const negTruth=negEncoded&&negWeight===0?'NEG effective=0 · 已编码，但本轮不参与最终 guidance':`NEG effective=${negWeight.toFixed(3)} · ${negEncoded?'已编码':'无用户 Negative 输入'}`;
    $('formula-list').replaceChildren(
      formula('K = min(Kmax, ceil(Ncontent / 75))',`Ncontent=${int(s.positive_input_tokens)}, K=${k}`, '每块固定 77 slots，其中最多 75 个内容 token。'),
      formula('Cₖ = CLIP(Tₖ),  Cₖ ∈ R^(77×hidden)',`77 × ${hidden||'hidden'} · K=${k}`,'每个 chunk 独立形成条件向量。'),
      formula('ε = uncond + CFG·(text−uncond)',`CFG=${cfg.toFixed(3)} · POS effective=${posWeight.toFixed(3)} · ${negTruth}`,'Token 被编码不等于实际参与 guidance；CFG=1 时 Negative 的有效权重为 0。'),
      formula('ε̄ₜ = (1/K) Σₖ εₜ⁽ᵏ⁾',`step ${step}/${total||'—'} · K=${k}`,'当前默认仍是多 chunk prediction 等权均值；H6R3 诊断阶段暂不改变。'),
      formula('Iₖ = |εₜ⁽ᵏ⁾ − ε̄ₜ|',`H6 influence samples=${arr(s.influence_samples).length}`,'H6 展示的是 chunk prediction 相对 fused prediction 的差异，不是 cross-attention。'),
      formula('zₜ₋₁ = Scheduler(zₜ, ε̄ₜ, t)',`t=${num(s.timestep).toFixed(2)} · seen=${Boolean(s.scheduler_seen)}`,'Scheduler 使用的 ε̄ₜ 与 H2 完全相同。')
    );
    const grid=$('tensor-grid');grid.replaceChildren();[['CFG',cfg.toFixed(3)],['NEG effective',negWeight.toFixed(3)],['CLIP seq',int(s.seq_len)||'—'],['Hidden',hidden||'—'],['Latent',int(s.latent_width)?`${int(s.latent_width)}×${int(s.latent_height)}`:'—'],['Chunks',k],['Influence',arr(s.influence_samples).length],['Scheduler',s.scheduler_seen?'YES':'NO']].forEach(([a,b])=>{const d=document.createElement('div');d.className='tensor-item';d.innerHTML='<span></span><strong></strong>';d.children[0].textContent=a;d.children[1].textContent=String(b);grid.appendChild(d);});
  }
'''
    text = replace_once(text, old, new, "H6R3 guidance mechanism")
    path.write_text(text, encoding="utf-8")


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: patch_h6_v6_semantic_fidelity.py <h6r2-patched-local-dream-root>", file=sys.stderr)
        return 2
    root = Path(sys.argv[1]).resolve()
    patch_gradle(root)
    patch_pipeline(root)
    patch_main_cpp(root)
    patch_service(root)
    patch_screen(root)
    patch_js(root)
    print("S24U_IMAGE_HARNESS_H6R3_CFG_TRUTH_APPLIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
