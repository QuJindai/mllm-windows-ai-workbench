#!/usr/bin/env python3
from pathlib import Path
import sys


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one literal match, found {count}")
    return text.replace(old, new, 1)


def patch_html(root: Path) -> None:
    path = root / "app/src/main/assets/s24u_microscope/index.html"
    text = path.read_text(encoding="utf-8")
    old = '''      <article class="card">
        <div class="section-head"><div><span class="kicker">ARCHITECTURE</span><h2>真实计算链</h2></div><span id="step-badge" class="badge">—</span></div>
        <div id="pipeline" class="pipeline">
          <div class="node" data-node="prompt"><b>Prompt</b><small>文本</small></div><i>›</i>
          <div class="node" data-node="token"><b>Token</b><small>Chunk × K</small></div><i>›</i>
          <div class="node" data-node="clip"><b>CLIP</b><small>77 × hidden</small></div><i>›</i>
          <div class="node" data-node="unet"><b>UNet</b><small>εₜ⁽ᵏ⁾</small></div><i>›</i>
          <div class="node" data-node="scheduler"><b>Scheduler</b><small>ε̄ₜ → zₜ₋₁</small></div><i>›</i>
          <div class="node" data-node="vae"><b>VAE</b><small>decode</small></div><i>›</i>
          <div class="node" data-node="image"><b>Image</b><small>RGB</small></div>
        </div>
      </article>
'''
    new = '''      <article class="card runtime-graph-card">
        <div class="section-head"><div><span class="kicker">RUNTIME COMPUTE GRAPH</span><h2>真实运行时计算链</h2></div><span id="step-badge" class="badge">—</span></div>
        <p class="subtle">每个节点显示真实 backend、shape、调用次数、耗时和 executed/skipped 状态。点击节点展开输入来源、输出去向和本轮实际值。</p>
        <div id="runtime-graph" class="runtime-graph"></div>
      </article>
'''
    text = replace_once(text, old, new, "runtime graph HTML")
    old_attention = '''        <div class="attention-state"><strong>当前不可观测：Cross-attention 未导出</strong><p>这是当前 QNN 编译图的能力缺口，不是页面加载失败。编译图没有把 cross-attention 中间 tensor 声明为图输出；H6 的 conditioning influence 只说明各 chunk prediction 与 fused prediction 的差异，不能冒充 token-level attention。</p></div>
'''
    new_attention = '''        <div class="attention-state"><strong>Production QNN 图未导出 Cross-attention</strong><p>当前 production <code>unet.bin</code> 的外部契约只返回最终 <code>out_sample</code>，内部 cross-attention tensor 没有被声明为 graph output，所以 APK 运行时无法临时读取。H6R3 的 conditioning influence 不是 attention。真正 token-level 词图归因进入 H7：单独构建 <strong>Debug UNet Graph</strong>，只暴露选定 Down / Mid / Up attention 输出，Production UNet 保持原样。</p></div>
'''
    text = replace_once(text, old_attention, new_attention, "attention capability wording")
    path.write_text(text, encoding="utf-8")


def patch_js(root: Path) -> None:
    path = root / "app/src/main/assets/s24u_microscope/microscope.js"
    text = path.read_text(encoding="utf-8")
    start = text.index("  function pipelineState(s) {")
    end = text.index("  function metric(label,value)", start)
    new = r'''  function sumPhaseDuration(s,phase){return arr(s.events).filter(e=>e.phase===phase).reduce((sum,e)=>sum+Math.max(0,int(e.duration_ms)),0);}
  function renderRuntimeGraph(s){
    const posChunks=Math.max(arr(s.positive_chunk_tokens).length,1),negChunks=Math.max(arr(s.negative_chunk_tokens).length,1),k=Math.max(posChunks,negChunks),fusion=txt(s.fusion_mode,'equal_mean'),activeChunks=fusion==='first_only'?1:k,steps=Math.max(int(s.diffusion_total),int(s.steps),0),hidden=int(s.hidden_dim),lw=int(s.latent_width),lh=int(s.latent_height),done=txt(s.phase)==='complete';
    const clipCalls=k,unetCalls=activeChunks*steps,schedulerCalls=steps,unetDuration=sumPhaseDuration(s,'unet_step'),schedulerDuration=sumPhaseDuration(s,'scheduler_step'),clipDuration=int(s.clip_ms),vaeDuration=int(s.vae_ms);
    const qnn=txt(s.backend).includes('NPU')||txt(s.backend).includes('QNN');
    const nodes=[
      {name:'Prompt',backend:'App / CPU',shape:`POS ${int(s.positive_input_tokens)} · NEG ${int(s.negative_input_tokens)} tokens`,call_count:1,duration_ms:sumPhaseDuration(s,'prompt'),execution_state:int(s.positive_input_tokens)>0?'executed':'waiting',input_source:'用户原始输入（不做语义改写）',output_destination:'Tokenizer / Prompt Processor'},
      {name:'Tokenizer / Chunker',backend:'C++ / CPU',shape:`POS [${arr(s.positive_chunk_tokens).join(', ')}] · NEG [${arr(s.negative_chunk_tokens).join(', ')}]`,call_count:1,duration_ms:sumPhaseDuration(s,'prompt'),execution_state:arr(s.positive_chunk_tokens).length?'executed':'waiting',input_source:'Prompt',output_destination:`${k} 个 fixed-77 CLIP chunk`},
      {name:'CLIP-1 / CLIP-2',backend:'MNN / CPU',shape:`${k} × 77 × ${hidden||'hidden'} · pooled 1280`,call_count:clipCalls,duration_ms:clipDuration,execution_state:Boolean(s.unet_seen)||clipDuration>0?'executed':'waiting',input_source:'每个 Token Chunk',output_destination:'Conditioning hidden / text_embeds / time_ids'},
      {name:'Conditioning',backend:'CPU memory',shape:`K=${k} · encoder_hidden_states 1×77×${hidden||2048}`,call_count:k,duration_ms:0,execution_state:Boolean(s.unet_seen)?'resident':'waiting',input_source:'CLIP-1 / CLIP-2',output_destination:'CFG / Guidance → UNet'},
      {name:'CFG / Guidance',backend:'CPU / vector math',shape:`CFG=${num(s.cfg_value,num(s.cfg,1)).toFixed(3)} · NEG effective=${num(s.negative_effective_weight).toFixed(3)}`,call_count:unetCalls,duration_ms:0,execution_state:Boolean(s.unet_seen)?(Boolean(s.skip_uncond)?'uncond skipped':'executed'):'waiting',input_source:'Positive/Negative UNet prediction',output_destination:'每个 chunk 的 εₜ⁽ᵏ⁾'},
      {name:`UNet Chunk 1..${activeChunks}`,backend:qnn?'QNN / HTP':'MNN / CPU',shape:`${activeChunks} × [1×4×${lw||'H'}×${lh||'W'}] → ε`,call_count:unetCalls,duration_ms:unetDuration,execution_state:Boolean(s.unet_seen)?'executed':'waiting',input_source:'zₜ + conditioning + timestep',output_destination:'Chunk Fusion'},
      {name:'Chunk Fusion',backend:'CPU / xtensor',shape:`mode=${fusion} · weights=[${arr(s.fusion_weights).map(v=>num(v).toFixed(3)).join(', ')}]`,call_count:steps,duration_ms:0,execution_state:Boolean(s.unet_seen)?'executed':'waiting',input_source:`${activeChunks} 个 chunk prediction`,output_destination:'fused ε̄ₜ'},
      {name:'Scheduler',backend:'Scheduler / CPU',shape:`zₜ 1×4×${lw||'H'}×${lh||'W'} + ε̄ₜ → zₜ₋₁`,call_count:schedulerCalls,duration_ms:schedulerDuration,execution_state:Boolean(s.scheduler_seen)?'executed':'waiting',input_source:'当前 latent + fused prediction + timestep',output_destination:'Latent zₜ'},
      {name:'Latent zₜ',backend:'CPU memory',shape:`1×4×${lw||'H'}×${lh||'W'} · ${arr(s.latent_maps).length} states`,call_count:arr(s.latent_maps).length,duration_ms:0,execution_state:arr(s.latent_maps).length?'captured':'waiting',input_source:'Scheduler output',output_destination:'下一 diffusion step / Final VAE Decode'},
      {name:'Final VAE Decode',backend:qnn?'QNN / HTP':'MNN / CPU',shape:`1×4×${lw||'H'}×${lh||'W'} → 1×3×${int(s.width)}×${int(s.height)}`,call_count:done||vaeDuration>0?1:0,duration_ms:vaeDuration,execution_state:done||vaeDuration>0?'executed':'waiting',input_source:'最终 latent',output_destination:'RGB Image'},
      {name:'Image',backend:'App / UI',shape:`${int(s.width)}×${int(s.height)}×3`,call_count:done?1:0,duration_ms:int(s.total_ms),execution_state:done?'complete':'waiting',input_source:'Final VAE Decode',output_destination:'生成结果 / 历史'}
    ];
    const graph=$('runtime-graph');graph.replaceChildren();nodes.forEach((data,i)=>{const node=document.createElement('button');node.className=`runtime-node state-${data.execution_state.replaceAll(' ','-')}`;node.innerHTML='<div class="runtime-node-head"><b></b><span></span></div><div class="runtime-node-grid"></div><div class="runtime-node-detail"></div>';node.querySelector('b').textContent=data.name;node.querySelector('.runtime-node-head span').textContent=data.execution_state;const grid=node.querySelector('.runtime-node-grid');[['backend',data.backend],['shape',data.shape],['calls',data.call_count],['duration',`${data.duration_ms} ms`]].forEach(([a,b])=>{const cell=document.createElement('span');cell.innerHTML='<small></small><strong></strong>';cell.children[0].textContent=a;cell.children[1].textContent=String(b);grid.appendChild(cell);});const detail=node.querySelector('.runtime-node-detail');detail.textContent=`input_source: ${data.input_source} → output_destination: ${data.output_destination}`;node.addEventListener('click',()=>node.classList.toggle('expanded'));graph.appendChild(node);if(i<nodes.length-1){const arrow=document.createElement('div');arrow.className='runtime-arrow';arrow.textContent='↓';graph.appendChild(arrow);}});
    const step=int(s.diffusion_step),total=int(s.diffusion_total);$('step-badge').textContent=total>0?`step ${step}/${total} · t=${num(s.timestep).toFixed(0)}`:'等待 step';
  }

'''
    text = text[:start] + new + text[end:]
    text = replace_once(
        text,
        "if(activePanel==='overview'){pipelineState(s);renderBudget(s);renderTimeline(s,force);}",
        "if(activePanel==='overview'){renderRuntimeGraph(s);renderBudget(s);renderTimeline(s,force);}",
        "overview runtime graph",
    )
    path.write_text(text, encoding="utf-8")


def patch_css(root: Path) -> None:
    path = root / "app/src/main/assets/s24u_microscope/microscope.css"
    text = path.read_text(encoding="utf-8")
    text += '''
/* H6R3 Runtime Compute Graph */
.runtime-graph{display:flex;flex-direction:column;gap:6px;margin-top:14px}.runtime-node{width:100%;border:1px solid var(--line);background:var(--surface);border-radius:18px;padding:14px;text-align:left}.runtime-node-head{display:flex;justify-content:space-between;gap:12px;align-items:center}.runtime-node-head span{font-size:12px;font-weight:800;text-transform:uppercase;color:var(--muted)}.runtime-node-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin-top:10px}.runtime-node-grid span{display:flex;flex-direction:column;min-width:0}.runtime-node-grid small{color:var(--muted);font-size:11px}.runtime-node-grid strong{font-size:13px;overflow-wrap:anywhere}.runtime-node-detail{display:none;margin-top:12px;padding-top:10px;border-top:1px solid var(--line);color:var(--muted);font-size:12px;line-height:1.5}.runtime-node.expanded .runtime-node-detail{display:block}.runtime-arrow{text-align:center;color:var(--muted);font-weight:900}.runtime-node.state-executed,.runtime-node.state-complete,.runtime-node.state-captured,.runtime-node.state-resident{border-color:color-mix(in srgb,var(--primary) 45%,var(--line))}.runtime-node.state-uncond-skipped{border-color:#d9a33d}
'''
    path.write_text(text, encoding="utf-8")


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: patch_h6_v10_runtime_graph.py <h6r3-task5-root>", file=sys.stderr)
        return 2
    root = Path(sys.argv[1]).resolve()
    patch_html(root)
    patch_js(root)
    patch_css(root)
    print("S24U_IMAGE_HARNESS_H6R3_RUNTIME_GRAPH_APPLIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
