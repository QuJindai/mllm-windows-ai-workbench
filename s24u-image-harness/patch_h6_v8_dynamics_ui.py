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
    old = '''      <article class="card process-card">
        <div class="section-head"><div><span class="kicker">PROCESS EVIDENCE</span><h2>逐 step 生成过程</h2></div><span id="preview-badge" class="badge">0 帧</span></div>
        <p class="subtle">优先显示 Local Dream 原生 <code>renderPreview()</code> 的真实 VAE 帧；当 SDXL QNN 低内存模式禁止逐 step VAE decode 时，自动回退显示同一步真实 scheduler latent，不增加额外模型推理。</p>
        <div class="viewer">
          <img id="process-main-image" alt="真实 diffusion 过程图">
          <div id="process-empty" class="viewer-empty">等待真实过程证据；低内存模式有 latent 时会自动回退显示。</div>
        </div>
        <input id="process-scrubber" class="scrubber" type="range" min="0" max="0" value="0" step="1" aria-label="process step">
        <div id="process-meta" class="viewer-meta">—</div>
        <div id="process-thumbs" class="thumbs"></div>
      </article>
'''
    new = '''      <article class="card process-card">
        <div class="section-head"><div><span class="kicker">PROCESS DYNAMICS</span><h2>逐 step 状态变化</h2></div><span id="preview-badge" class="badge">0 step</span></div>
        <p class="subtle">主视图显示相邻状态的真实变化 <code>Δzₜ = zₜ₋₁ − zₜ</code>，并联动 L2、Mean |Δz|、相邻 latent cosine、mean/std 与真实 UNet/Scheduler 耗时。它不再复用内部 latent 2×2 通道图。</p>
        <div class="viewer">
          <img id="process-main-image" alt="真实 latent delta 变化图">
          <div id="process-empty" class="viewer-empty">等待相邻 scheduler latent 的真实变化证据。</div>
        </div>
        <input id="process-scrubber" class="scrubber" type="range" min="0" max="0" value="0" step="1" aria-label="process dynamics step">
        <div id="dynamics-metrics" class="metrics compact"></div>
        <div id="process-meta" class="viewer-meta">—</div>
        <div id="dynamics-series" class="influence-bars"></div>
      </article>

      <article id="decoded-preview-card" class="card process-card">
        <div class="section-head"><div><span class="kicker">DECODED PREVIEW</span><h2>真实 VAE 过程预览</h2></div><span id="decoded-badge" class="badge">0 帧</span></div>
        <p id="decoded-note" class="subtle">只有 backend 实际执行逐 step VAE decode 时才显示；SDXL QNN low-RAM 不会用 latent 图冒充 decoded preview。</p>
        <div class="viewer"><img id="decoded-main-image" alt="真实 VAE decoded preview"><div id="decoded-empty" class="viewer-empty">本轮没有逐 step VAE decode。</div></div>
        <input id="decoded-scrubber" class="scrubber" type="range" min="0" max="0" value="0" step="1" aria-label="decoded preview step">
        <div id="decoded-meta" class="viewer-meta">—</div>
        <div id="decoded-thumbs" class="thumbs"></div>
      </article>
'''
    text = replace_once(text, old, new, "process dynamics HTML")
    path.write_text(text, encoding="utf-8")


def patch_js(root: Path) -> None:
    path = root / "app/src/main/assets/s24u_microscope/microscope.js"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '  let lastPreviewCount = -1;\n  let lastLatentCount = -1;\n',
        '  let lastPreviewCount = -1;\n  let lastDynamicsCount = -1;\n  let lastLatentCount = -1;\n',
        "dynamics JS state",
    )
    text = replace_once(
        text,
        "    scheduler_step:'Scheduler 正在把 zₜ 更新为 zₜ₋₁。', latent_map:'已捕捉 scheduler 更新后的真实 4 通道 latent。',\n",
        "    scheduler_step:'Scheduler 正在把 zₜ 更新为 zₜ₋₁。', latent_delta:'正在计算相邻 latent 的真实 Δz 动力学。', latent_map:'已捕捉 scheduler 更新后的真实 4 通道 latent。',\n",
        "dynamics phase copy",
    )
    start = text.index('  function imageSrc(frame)')
    end = text.index('  function influenceSteps(samples)')
    process_block = r'''  function imageSrc(frame){ const format=txt(frame.format,'jpeg').toLowerCase(); return `data:image/${format};base64,${frame.image_base64||''}`; }
  function showLatentFrame(frames,index){const image=$('latent-main-image'),empty=$('latent-empty'),meta=$('latent-meta');if(!frames.length||index<0){image.classList.remove('ready');image.removeAttribute('src');empty.style.display='block';meta.textContent='—';return;}const f=frames[clamp(index,0,frames.length-1)];image.src=imageSrc(f);image.classList.add('ready');empty.style.display='none';meta.textContent=`Latent step ${int(f.diffusion_step,index+1)} · t=${num(f.timestep).toFixed(0)} · 4×${int(f.latent_width)}×${int(f.latent_height)}`;}
  function renderProcessDynamics(s,force=false){
    const samples=arr(s.dynamics_samples);if(!force&&samples.length===lastDynamicsCount)return;lastDynamicsCount=samples.length;$('preview-badge').textContent=`${samples.length} step`;
    const scrub=$('process-scrubber');scrub.max=String(Math.max(0,samples.length-1));if(selectedPreview<0||selectedPreview>=samples.length)selectedPreview=samples.length?samples.length-1:-1;scrub.value=String(Math.max(0,selectedPreview));
    const image=$('process-main-image'),empty=$('process-empty'),meta=$('process-meta'),metrics=$('dynamics-metrics');
    if(!samples.length){image.classList.remove('ready');image.removeAttribute('src');empty.style.display='block';meta.textContent='—';metrics.replaceChildren();$('dynamics-series').replaceChildren();return;}
    const sample=samples[clamp(selectedPreview,0,samples.length-1)];if(sample.image_base64){image.src=imageSrc(sample);image.classList.add('ready');empty.style.display='none';}else{image.classList.remove('ready');image.removeAttribute('src');empty.style.display='block';}
    metrics.replaceChildren(metric('L2(Δz)',num(sample.delta_l2).toFixed(4)),metric('Mean |Δz|',num(sample.delta_mean_abs).toFixed(6)),metric('cos(zₜ,zₜ₋₁)',num(sample.latent_cosine).toFixed(6)),metric('latent μ / σ',`${num(sample.latent_mean).toFixed(4)} / ${num(sample.latent_std).toFixed(4)}`),metric('UNet',`${int(sample.unet_ms)} ms`),metric('Scheduler',`${int(sample.scheduler_ms)} ms`));
    meta.textContent=`Δz step ${int(sample.diffusion_step)}/${int(sample.diffusion_total)} · t=${num(sample.timestep).toFixed(0)} · 主图=四通道 Mean |Δz| 空间变化`;
    const max=Math.max(...samples.map(x=>num(x.delta_l2)),1e-12),series=$('dynamics-series');series.replaceChildren();samples.forEach(x=>{const row=document.createElement('div');row.className='influence-bar-row';const label=document.createElement('div');label.className='influence-bar-label';label.textContent=`Step ${int(x.diffusion_step)}`;const track=document.createElement('div');track.className='influence-bar-track';const fill=document.createElement('div');fill.className='influence-bar-fill';fill.style.width=`${clamp(num(x.delta_l2)/max*100,0,100)}%`;track.appendChild(fill);const value=document.createElement('div');value.className='influence-bar-value';value.textContent=num(x.delta_l2).toFixed(2);row.append(label,track,value);series.appendChild(row);});
  }
  function renderDecodedPreviews(s,force=false){const previews=arr(s.process_previews);if(!force&&previews.length===lastPreviewCount)return;lastPreviewCount=previews.length;$('decoded-badge').textContent=`${previews.length} 帧`;const scrub=$('decoded-scrubber');scrub.max=String(Math.max(0,previews.length-1));const index=previews.length?previews.length-1:-1;scrub.value=String(Math.max(0,index));const image=$('decoded-main-image'),empty=$('decoded-empty'),meta=$('decoded-meta'),thumbs=$('decoded-thumbs');thumbs.replaceChildren();if(!previews.length){image.classList.remove('ready');image.removeAttribute('src');empty.style.display='block';meta.textContent='本轮 backend 没有执行逐 step VAE decode；不使用 latent 图替代。';return;}const show=(i)=>{const f=previews[clamp(i,0,previews.length-1)];image.src=imageSrc(f);image.classList.add('ready');empty.style.display='none';meta.textContent=`真实 VAE 帧 ${int(f.preview_index,i+1)} · progress ${int(f.step)}/${int(f.total_steps)} · ${txt(f.format,'jpeg').toUpperCase()}`;};previews.forEach((f,i)=>{const b=document.createElement('button');b.className='thumb';const img=document.createElement('img');img.src=imageSrc(f);img.alt=`decoded ${i+1}`;b.appendChild(img);b.addEventListener('click',()=>{scrub.value=String(i);show(i);});thumbs.appendChild(b);});show(index);}
  function renderLatentState(s,force=false){const latents=arr(s.latent_maps);if(force||latents.length!==lastLatentCount){lastLatentCount=latents.length;$('latent-badge').textContent=`${latents.length} 帧`;const scrub=$('latent-scrubber');scrub.max=String(Math.max(0,latents.length-1));selectedLatent=latents.length?latents.length-1:-1;scrub.value=String(Math.max(0,selectedLatent));showLatentFrame(latents,selectedLatent);}}
  $('process-scrubber').addEventListener('input',(e)=>{if(!pendingSnapshot)return;selectedPreview=int(e.target.value);renderProcessDynamics(pendingSnapshot,true);});
  $('decoded-scrubber').addEventListener('input',(e)=>{if(!pendingSnapshot)return;const previews=arr(pendingSnapshot.process_previews),i=int(e.target.value);const image=$('decoded-main-image'),empty=$('decoded-empty'),meta=$('decoded-meta');if(!previews.length)return;const f=previews[clamp(i,0,previews.length-1)];image.src=imageSrc(f);image.classList.add('ready');empty.style.display='none';meta.textContent=`真实 VAE 帧 ${int(f.preview_index,i+1)} · progress ${int(f.step)}/${int(f.total_steps)} · ${txt(f.format,'jpeg').toUpperCase()}`;});
  $('latent-scrubber').addEventListener('input',(e)=>{if(!pendingSnapshot)return;selectedLatent=int(e.target.value);showLatentFrame(arr(pendingSnapshot.latent_maps),selectedLatent);});

'''
    text = text[:start] + process_block + text[end:]
    text = replace_once(
        text,
        "else if(activePanel==='process'){renderProcess(s,force);}",
        "else if(activePanel==='process'){renderProcessDynamics(s,force);renderDecodedPreviews(s,force);renderLatentState(s,force);}",
        "active process renderer",
    )
    text = replace_once(
        text,
        '''      if(media&&media.influence_samples_delta){
''',
        '''      if(media&&media.dynamics_samples_delta){
        const dynamics_samples_delta=arr(media.dynamics_samples_delta),samples=arr(pendingSnapshot.dynamics_samples).slice();
        dynamics_samples_delta.forEach((sample)=>{const key=int(sample.diffusion_step),idx=samples.findIndex(x=>int(x.diffusion_step)===key);if(idx>=0)samples[idx]=sample;else samples.push(sample);});
        pendingSnapshot.dynamics_samples=samples.slice(-8);
      }
      if(media&&media.influence_samples_delta){
''',
        "dynamics media receiver",
    )
    path.write_text(text, encoding="utf-8")


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: patch_h6_v8_dynamics_ui.py <h6r3-task3-root>", file=sys.stderr)
        return 2
    root = Path(sys.argv[1]).resolve()
    patch_html(root)
    patch_js(root)
    print("S24U_IMAGE_HARNESS_H6R3_DYNAMICS_UI_APPLIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
