#!/usr/bin/env python3
from pathlib import Path
import sys


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one literal match, found {count}")
    return text.replace(old, new, 1)


def patch_pipeline(root: Path) -> None:
    path = root / "app/src/main/cpp/src/Pipeline.hpp"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "  std::vector<float> channel_histograms;\n};\n",
        "  std::vector<float> channel_histograms;\n"
        "  int observed_clip_passes = 0;\n"
        "  int observed_unet_passes = 0;\n"
        "  int observed_scheduler_calls = 0;\n"
        "  int observed_vae_decodes = 0;\n"
        "  int64_t clip_total_ms = 0;\n"
        "  int64_t unet_total_ms = 0;\n"
        "  int64_t scheduler_total_ms = 0;\n"
        "  int64_t vae_total_ms = 0;\n"
        "  int64_t accounted_ms = 0;\n"
        "  int64_t unattributed_ms = 0;\n"
        "};\n",
        "runtime truth trace fields",
    )
    text = replace_once(
        text,
        '''    auto start_time = std::chrono::high_resolution_clock::now();
    auto emit_trace = [&](MicroscopeTraceEvent event) {
      event.elapsed_ms = elapsedMs(start_time);
      if (microscope_callback) microscope_callback(event);
    };
''',
        '''    auto start_time = std::chrono::high_resolution_clock::now();
    int observed_clip_passes = 0;
    int observed_unet_passes = 0;
    int observed_scheduler_calls = 0;
    int observed_vae_decodes = 0;
    int64_t clip_total_ms = 0;
    int64_t unet_total_ms = 0;
    int64_t scheduler_total_ms = 0;
    int64_t vae_total_ms = 0;
    auto emit_trace = [&](MicroscopeTraceEvent event) {
      event.elapsed_ms = elapsedMs(start_time);
      event.observed_clip_passes = observed_clip_passes;
      event.observed_unet_passes = observed_unet_passes;
      event.observed_scheduler_calls = observed_scheduler_calls;
      event.observed_vae_decodes = observed_vae_decodes;
      event.clip_total_ms = clip_total_ms;
      event.unet_total_ms = unet_total_ms;
      event.scheduler_total_ms = scheduler_total_ms;
      event.vae_total_ms = vae_total_ms;
      event.accounted_ms = clip_total_ms + unet_total_ms +
                           scheduler_total_ms + vae_total_ms;
      event.unattributed_ms =
          std::max<int64_t>(0, event.elapsed_ms - event.accounted_ms);
      if (microscope_callback) microscope_callback(event);
    };
''',
        "runtime cumulative counters",
    )

    # Count real decoded previews when the backend actually executes them.
    text = replace_once(
        text,
        '''      if (req.show_diffusion_process && previewSupported() &&
          (i - start_step) % req.show_diffusion_stride == 0) {
        progress_callback(current_step, total_run_steps,
                          renderPreview(req, latents));
      } else {
''',
        '''      if (req.show_diffusion_process && previewSupported() &&
          (i - start_step) % req.show_diffusion_stride == 0) {
        auto preview_vae_start = std::chrono::high_resolution_clock::now();
        std::string preview_image = renderPreview(req, latents);
        const auto preview_vae_ms = elapsedMs(preview_vae_start);
        observed_vae_decodes++;
        vae_total_ms += preview_vae_ms;
        progress_callback(current_step, total_run_steps, preview_image);
      } else {
''',
        "runtime preview VAE counter",
    )

    text = replace_once(
        text,
        '''    auto clip_dur = elapsedMs(clip_start);
    std::cout << "CLIP dur: " << clip_dur << "ms\n";
''',
        '''    auto clip_dur = elapsedMs(clip_start);
    clip_total_ms = clip_dur;
    observed_clip_passes = static_cast<int>(std::count_if(
        conds.begin(), conds.end(), [](const Conditioning &c) {
          return c.positive_clip_executed || c.negative_clip_executed;
        }));
    std::cout << "CLIP dur: " << clip_dur << "ms\n";
''',
        "runtime CLIP cumulative truth",
    )

    text = replace_once(
        text,
        '''      for (size_t chunk_index = 0; chunk_index < active_chunk_count; ++chunk_index) {
        auto &chunk_cond = conds[chunk_index];
        xt::xarray<float> chunk_pred;
        if (unet_tiled) {
''',
        '''      for (size_t chunk_index = 0; chunk_index < active_chunk_count; ++chunk_index) {
        auto &chunk_cond = conds[chunk_index];
        xt::xarray<float> chunk_pred;
        auto chunk_unet_start = std::chrono::high_resolution_clock::now();
        if (unet_tiled) {
''',
        "runtime per-chunk UNet start",
    )
    text = replace_once(
        text,
        '''        }
        chunk_predictions.push_back(chunk_pred);
        noise_pred = xt::eval(noise_pred + chunk_pred);
''',
        '''        }
        observed_unet_passes++;
        unet_total_ms += elapsedMs(chunk_unet_start);
        chunk_predictions.push_back(chunk_pred);
        noise_pred = xt::eval(noise_pred + chunk_pred);
''',
        "runtime per-chunk UNet accumulate",
    )
    text = replace_once(
        text,
        '''      auto scheduler_dur = elapsedMs(scheduler_start);
      MicroscopeTraceEvent scheduler_trace;
''',
        '''      auto scheduler_dur = elapsedMs(scheduler_start);
      observed_scheduler_calls++;
      scheduler_total_ms += scheduler_dur;
      MicroscopeTraceEvent scheduler_trace;
''',
        "runtime scheduler accumulate",
    )
    text = replace_once(
        text,
        '''    auto vae_dec_dur = elapsedMs(vae_dec_start);
    std::cout << "VAE Dec dur: " << vae_dec_dur << "ms\n";
''',
        '''    auto vae_dec_dur = elapsedMs(vae_dec_start);
    observed_vae_decodes++;
    vae_total_ms += vae_dec_dur;
    std::cout << "VAE Dec dur: " << vae_dec_dur << "ms\n";
''',
        "runtime final VAE accumulate",
    )
    path.write_text(text, encoding="utf-8")


def patch_main(root: Path) -> None:
    path = root / "app/src/main/cpp/src/main.cpp"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '''                        {"channel_histograms", trace.channel_histograms},
                        {"image_base64", trace.image_base64}};
''',
        '''                        {"channel_histograms", trace.channel_histograms},
                        {"observed_clip_passes", trace.observed_clip_passes},
                        {"observed_unet_passes", trace.observed_unet_passes},
                        {"observed_scheduler_calls", trace.observed_scheduler_calls},
                        {"observed_vae_decodes", trace.observed_vae_decodes},
                        {"clip_total_ms", trace.clip_total_ms},
                        {"unet_total_ms", trace.unet_total_ms},
                        {"scheduler_total_ms", trace.scheduler_total_ms},
                        {"vae_total_ms", trace.vae_total_ms},
                        {"accounted_ms", trace.accounted_ms},
                        {"unattributed_ms", trace.unattributed_ms},
                        {"image_base64", trace.image_base64}};
''',
        "runtime truth SSE serialization",
    )
    path.write_text(text, encoding="utf-8")


def patch_service(root: Path) -> None:
    path = root / "app/src/main/java/io/github/xororz/localdream/service/BackgroundGenerationService.kt"
    text = path.read_text(encoding="utf-8")
    runtime_fields = '''        val observedClipPasses: Int = 0,
        val observedUnetPasses: Int = 0,
        val observedSchedulerCalls: Int = 0,
        val observedVaeDecodes: Int = 0,
        val clipTotalMs: Long = 0L,
        val unetTotalMs: Long = 0L,
        val schedulerTotalMs: Long = 0L,
        val vaeTotalMs: Long = 0L,
        val accountedMs: Long = 0L,
        val unattributedMs: Long = 0L,
'''
    text = replace_once(
        text,
        '''        val channelHistograms: List<Float> = emptyList(),
    )

    data class MicroscopeSnapshot(
''',
        '''        val channelHistograms: List<Float> = emptyList(),
''' + runtime_fields + '''    )

    data class MicroscopeSnapshot(
''',
        "event runtime truth fields",
    )
    text = replace_once(
        text,
        '''        val dynamicsSamples: List<DynamicsSample> = emptyList(),
    )

    sealed class GenerationState {
''',
        '''        val dynamicsSamples: List<DynamicsSample> = emptyList(),
''' + runtime_fields + '''    )

    sealed class GenerationState {
''',
        "snapshot runtime truth fields",
    )
    text = replace_once(
        text,
        '''            channelHistograms = jsonFloatList(message, "channel_histograms"),
        )
''',
        '''            channelHistograms = jsonFloatList(message, "channel_histograms"),
            observedClipPasses = message.optInt("observed_clip_passes", 0),
            observedUnetPasses = message.optInt("observed_unet_passes", 0),
            observedSchedulerCalls = message.optInt("observed_scheduler_calls", 0),
            observedVaeDecodes = message.optInt("observed_vae_decodes", 0),
            clipTotalMs = message.optLong("clip_total_ms", 0L),
            unetTotalMs = message.optLong("unet_total_ms", 0L),
            schedulerTotalMs = message.optLong("scheduler_total_ms", 0L),
            vaeTotalMs = message.optLong("vae_total_ms", 0L),
            accountedMs = message.optLong("accounted_ms", 0L),
            unattributedMs = message.optLong("unattributed_ms", 0L),
        )
''',
        "runtime truth parser",
    )
    # Store cumulative counters from every trace. They are monotonic native
    # facts, so later media/influence events cannot lose earlier totals.
    anchor = '''            maxChunks = if (event.phase == "prompt") event.maxChunks else previous.maxChunks,
'''
    runtime_copy = '''            observedClipPasses = maxOf(previous.observedClipPasses, event.observedClipPasses),
            observedUnetPasses = maxOf(previous.observedUnetPasses, event.observedUnetPasses),
            observedSchedulerCalls = maxOf(previous.observedSchedulerCalls, event.observedSchedulerCalls),
            observedVaeDecodes = maxOf(previous.observedVaeDecodes, event.observedVaeDecodes),
            clipTotalMs = maxOf(previous.clipTotalMs, event.clipTotalMs),
            unetTotalMs = maxOf(previous.unetTotalMs, event.unetTotalMs),
            schedulerTotalMs = maxOf(previous.schedulerTotalMs, event.schedulerTotalMs),
            vaeTotalMs = maxOf(previous.vaeTotalMs, event.vaeTotalMs),
            accountedMs = maxOf(previous.accountedMs, event.accountedMs),
            unattributedMs = if (event.elapsedMs >= previous.totalMs) event.unattributedMs else previous.unattributedMs,
'''
    text = replace_once(text, anchor, anchor + runtime_copy, "runtime truth reducer")
    path.write_text(text, encoding="utf-8")


def patch_screen(root: Path) -> None:
    path = root / "app/src/main/java/io/github/xororz/localdream/ui/screens/ModelRunScreen.kt"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '            put("total_ms", microscope.totalMs)\n',
        '            put("total_ms", microscope.totalMs)\n'
        '            put("observed_clip_passes", microscope.observedClipPasses)\n'
        '            put("observed_unet_passes", microscope.observedUnetPasses)\n'
        '            put("observed_scheduler_calls", microscope.observedSchedulerCalls)\n'
        '            put("observed_vae_decodes", microscope.observedVaeDecodes)\n'
        '            put("clip_total_ms", microscope.clipTotalMs)\n'
        '            put("unet_total_ms", microscope.unetTotalMs)\n'
        '            put("scheduler_total_ms", microscope.schedulerTotalMs)\n'
        '            put("vae_total_ms", microscope.vaeTotalMs)\n'
        '            put("accounted_ms", microscope.accountedMs)\n'
        '            put("unattributed_ms", microscope.unattributedMs)\n',
        "runtime truth WebView payload",
    )
    path.write_text(text, encoding="utf-8")


def patch_js(root: Path) -> None:
    path = root / "app/src/main/assets/s24u_microscope/microscope.js"
    text = path.read_text(encoding="utf-8")
    start = text.index("  function sumPhaseDuration(s,phase)")
    end = text.index("  function metric(label,value)", start)
    graph = r'''  function renderRuntimeGraph(s){
    const posChunks=Math.max(arr(s.positive_chunk_tokens).length,1),negChunks=Math.max(arr(s.negative_chunk_tokens).length,1),k=Math.max(posChunks,negChunks),fusion=txt(s.fusion_mode,'equal_mean'),activeChunks=fusion==='first_only'?1:k,steps=Math.max(int(s.diffusion_total),int(s.steps),0),hidden=int(s.hidden_dim),lw=int(s.latent_width),lh=int(s.latent_height),done=txt(s.phase)==='complete',qnn=txt(s.backend).includes('NPU')||txt(s.backend).includes('QNN');
    const totals={clip:int(s.clip_total_ms),unet:int(s.unet_total_ms),scheduler:int(s.scheduler_total_ms),vae:int(s.vae_total_ms),accounted:int(s.accounted_ms),unattributed:int(s.unattributed_ms),total:int(s.total_ms)};
    const nodes=[
      {name:'TIME ACCOUNTING',backend:'native cumulative',shape:`Total ${totals.total} ms · Accounted ${totals.accounted} ms · Unattributed ${totals.unattributed} ms`,expected_calls:'—',observed_calls:'—',duration_ms:totals.accounted,execution_state:done?'complete':'live',input_source:'Pipeline::generate monotonic counters',output_destination:'runtime truth ledger'},
      {name:'Prompt',backend:'App / CPU',shape:`POS ${int(s.positive_input_tokens)} · NEG ${int(s.negative_input_tokens)} tokens`,expected_calls:1,observed_calls:'—',duration_ms:'—',execution_state:int(s.positive_input_tokens)>0?'executed':'waiting',input_source:'用户原始输入',output_destination:'Tokenizer / Prompt Processor'},
      {name:'Tokenizer / Chunker',backend:'C++ / CPU',shape:`POS [${arr(s.positive_chunk_tokens).join(', ')}] · NEG [${arr(s.negative_chunk_tokens).join(', ')}]`,expected_calls:1,observed_calls:'—',duration_ms:'—',execution_state:arr(s.positive_chunk_tokens).length?'executed':'waiting',input_source:'Prompt',output_destination:`${k} 个 direct token-preserving fixed-77 chunk`},
      {name:'CLIP-1 / CLIP-2',backend:'MNN / CPU',shape:`${k} × 77 × ${hidden||'hidden'} · pooled 1280`,expected_calls:k,observed_calls:int(s.observed_clip_passes),duration_ms:totals.clip,execution_state:int(s.observed_clip_passes)>0?'executed':'cached / waiting',input_source:'每个 direct Token Chunk',output_destination:'Conditioning hidden / text_embeds / time_ids'},
      {name:'Conditioning',backend:'CPU memory',shape:`K=${k} · encoder_hidden_states 1×77×${hidden||2048}`,expected_calls:k,observed_calls:'—',duration_ms:'—',execution_state:Boolean(s.unet_seen)?'resident':'waiting',input_source:'CLIP-1 / CLIP-2',output_destination:'CFG / Guidance → UNet'},
      {name:'CFG / Guidance',backend:'CPU / vector math',shape:`CFG=${num(s.cfg_value,num(s.cfg,1)).toFixed(3)} · NEG effective=${num(s.negative_effective_weight).toFixed(3)}`,expected_calls:activeChunks*steps,observed_calls:'—',duration_ms:'—',execution_state:Boolean(s.unet_seen)?(Boolean(s.skip_uncond)?'uncond skipped':'executed'):'waiting',input_source:'Positive/Negative UNet prediction',output_destination:'每个 chunk 的 εₜ⁽ᵏ⁾'},
      {name:`UNet Chunk 1..${activeChunks}`,backend:qnn?'QNN / HTP':'MNN / CPU',shape:`${activeChunks} × [1×4×${lw||'H'}×${lh||'W'}] → ε`,expected_calls:activeChunks*steps,observed_calls:int(s.observed_unet_passes),duration_ms:totals.unet,execution_state:int(s.observed_unet_passes)>0?'executed':'waiting',input_source:'zₜ + conditioning + timestep',output_destination:'Chunk Fusion'},
      {name:'Chunk Fusion',backend:'CPU / xtensor',shape:`mode=${fusion} · weights=[${arr(s.fusion_weights).map(v=>num(v).toFixed(3)).join(', ')}]`,expected_calls:steps,observed_calls:'—',duration_ms:'—',execution_state:Boolean(s.unet_seen)?'executed':'waiting',input_source:`${activeChunks} 个 chunk prediction`,output_destination:'fused ε̄ₜ'},
      {name:'Scheduler',backend:'Scheduler / CPU',shape:`zₜ 1×4×${lw||'H'}×${lh||'W'} + ε̄ₜ → zₜ₋₁`,expected_calls:steps,observed_calls:int(s.observed_scheduler_calls),duration_ms:totals.scheduler,execution_state:int(s.observed_scheduler_calls)>0?'executed':'waiting',input_source:'当前 latent + fused prediction + timestep',output_destination:'Latent zₜ'},
      {name:'Latent zₜ',backend:'CPU memory',shape:`1×4×${lw||'H'}×${lh||'W'} · ${arr(s.latent_maps).length} captured states`,expected_calls:steps,observed_calls:arr(s.latent_maps).length,duration_ms:'—',execution_state:arr(s.latent_maps).length?'captured':'waiting',input_source:'Scheduler output',output_destination:'下一 diffusion step / Final VAE Decode'},
      {name:'VAE Decode',backend:qnn?'QNN / HTP':'MNN / CPU',shape:`1×4×${lw||'H'}×${lh||'W'} → 1×3×${int(s.width)}×${int(s.height)}`,expected_calls:1,observed_calls:int(s.observed_vae_decodes),duration_ms:totals.vae,execution_state:int(s.observed_vae_decodes)>0?'executed':'waiting',input_source:'最终 latent + optional real process preview latent',output_destination:'RGB Image / decoded preview'},
      {name:'Image',backend:'App / UI',shape:`${int(s.width)}×${int(s.height)}×3`,expected_calls:1,observed_calls:done?1:0,duration_ms:totals.total,execution_state:done?'complete':'waiting',input_source:'Final VAE Decode',output_destination:'生成结果 / 历史'}
    ];
    const graph=$('runtime-graph');graph.replaceChildren();nodes.forEach((data,i)=>{const node=document.createElement('button');node.className=`runtime-node state-${data.execution_state.replaceAll(' ','-')}`;node.innerHTML='<div class="runtime-node-head"><b></b><span></span></div><div class="runtime-node-grid"></div><div class="runtime-node-detail"></div>';node.querySelector('b').textContent=data.name;node.querySelector('.runtime-node-head span').textContent=data.execution_state;const grid=node.querySelector('.runtime-node-grid');[['backend',data.backend],['shape',data.shape],['expected_calls',data.expected_calls],['observed_calls',data.observed_calls],['duration',data.duration_ms==='—'?'—':`${data.duration_ms} ms`]].forEach(([a,b])=>{const cell=document.createElement('span');cell.innerHTML='<small></small><strong></strong>';cell.children[0].textContent=a;cell.children[1].textContent=String(b);grid.appendChild(cell);});const detail=node.querySelector('.runtime-node-detail');detail.textContent=`input_source: ${data.input_source} → output_destination: ${data.output_destination}`;node.addEventListener('click',()=>node.classList.toggle('expanded'));graph.appendChild(node);if(i<nodes.length-1){const arrow=document.createElement('div');arrow.className='runtime-arrow';arrow.textContent='↓';graph.appendChild(arrow);}});
    const step=int(s.diffusion_step),total=int(s.diffusion_total);$('step-badge').textContent=total>0?`step ${step}/${total} · t=${num(s.timestep).toFixed(0)}`:'等待 step';
  }

'''
    text = text[:start] + graph + text[end:]

    dstart = text.index("  function renderDecodedPreviews(s,force=false)")
    dend = text.index("  $('process-scrubber')", dstart)
    decoded = r'''  function renderDecodedPreviews(s,force=false){
    const previews=arr(s.process_previews);if(!force&&previews.length===lastPreviewCount)return;lastPreviewCount=previews.length;
    const badge=$('decoded-badge'),scrub=$('decoded-scrubber'),image=$('decoded-main-image'),empty=$('decoded-empty'),meta=$('decoded-meta'),thumbs=$('decoded-thumbs'),viewer=image.closest('.viewer');thumbs.replaceChildren();
    if(!previews.length){badge.textContent='NOT EXECUTED';image.classList.remove('ready');image.removeAttribute('src');viewer.style.display='none';scrub.style.display='none';thumbs.style.display='none';empty.style.display='none';meta.textContent='NOT EXECUTED · 本轮 backend 没有执行逐 step VAE decode；Final VAE decode 仍由 Runtime Graph 单独计数。';return;}
    badge.textContent=`${previews.length} 帧`;viewer.style.display='';scrub.style.display='';thumbs.style.display='';scrub.max=String(Math.max(0,previews.length-1));const index=previews.length-1;scrub.value=String(index);
    const show=(i)=>{const f=previews[clamp(i,0,previews.length-1)];image.src=imageSrc(f);image.classList.add('ready');empty.style.display='none';meta.textContent=`真实 VAE 帧 ${int(f.preview_index,i+1)} · progress ${int(f.step)}/${int(f.total_steps)} · ${txt(f.format,'jpeg').toUpperCase()}`;};
    previews.forEach((f,i)=>{const b=document.createElement('button');b.className='thumb';const img=document.createElement('img');img.src=imageSrc(f);img.alt=`decoded ${i+1}`;b.appendChild(img);b.addEventListener('click',()=>{scrub.value=String(i);show(i);});thumbs.appendChild(b);});show(index);
  }
'''
    text = text[:dstart] + decoded + text[dend:]
    path.write_text(text, encoding="utf-8")


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: patch_h6_v12_runtime_truth.py <h6r4-token-root>", file=sys.stderr)
        return 2
    root = Path(sys.argv[1]).resolve()
    patch_pipeline(root)
    patch_main(root)
    patch_service(root)
    patch_screen(root)
    patch_js(root)
    print("S24U_IMAGE_HARNESS_H6R4_RUNTIME_TRUTH_APPLIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
