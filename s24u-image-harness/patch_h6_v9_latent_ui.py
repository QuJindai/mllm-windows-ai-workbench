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
        <div class="section-head"><div><span class="kicker">LATENT · 4 CHANNELS</span><h2>内部 latent 通道图</h2></div><span id="latent-badge" class="badge">0 帧</span></div>
        <p class="subtle">这是每个 scheduler step 后真实的 4 通道 latent，按通道归一化成 2×2 灰度图。它不是“UNet 每层特征图”，但是真实内部状态。</p>
        <div class="viewer latent-viewer">
          <img id="latent-main-image" alt="真实 latent 四通道图">
          <div id="latent-empty" class="viewer-empty">等待 latent trace…</div>
        </div>
        <input id="latent-scrubber" class="scrubber" type="range" min="0" max="0" value="0" step="1" aria-label="latent step">
        <div id="latent-meta" class="viewer-meta">—</div>
      </article>
'''
    new = '''      <article class="card process-card">
        <div class="section-head"><div><span class="kicker">LATENT STATE INSPECTOR</span><h2>内部 latent 状态</h2></div><span id="latent-badge" class="badge">0 帧</span></div>
        <p class="subtle">回答“这一时刻内部状态是什么”：C0–C3 分通道观察，并显示真实 min/max/mean/std/L2、32-bin 直方图和 4×4 通道相关矩阵。2×2 contact sheet 只保留为 Overview。</p>
        <input id="latent-scrubber" class="scrubber" type="range" min="0" max="0" value="0" step="1" aria-label="latent step">
        <div id="latent-meta" class="viewer-meta">—</div>
        <div id="latent-channel-grid" class="latent-channel-grid"></div>
        <div id="latent-channel-stats" class="metrics compact"></div>
        <div class="section-head minor"><div><span class="kicker">HISTOGRAM</span><h3>选中通道分布</h3></div></div>
        <div id="latent-histogram" class="latent-histogram"></div>
        <div class="section-head minor"><div><span class="kicker">CORRELATION</span><h3>4×4 通道相关矩阵</h3></div></div>
        <div id="latent-correlation" class="latent-correlation"></div>
        <div class="section-head minor"><div><span class="kicker">STEP COMPARE</span><h3>previous / current / final</h3></div></div>
        <div id="latent-compare" class="metrics compact"></div>
        <details><summary>Overview · 2×2 contact sheet</summary><div class="viewer latent-viewer"><img id="latent-main-image" alt="真实 latent 四通道 Overview"><div id="latent-empty" class="viewer-empty">等待 latent trace…</div></div></details>
      </article>
'''
    text = replace_once(text, old, new, "latent inspector HTML")
    path.write_text(text, encoding="utf-8")


def patch_js(root: Path) -> None:
    path = root / "app/src/main/assets/s24u_microscope/microscope.js"
    text = path.read_text(encoding="utf-8")
    old = """  function showLatentFrame(frames,index){const image=$('latent-main-image'),empty=$('latent-empty'),meta=$('latent-meta');if(!frames.length||index<0){image.classList.remove('ready');image.removeAttribute('src');empty.style.display='block';meta.textContent='—';return;}const f=frames[clamp(index,0,frames.length-1)];image.src=imageSrc(f);image.classList.add('ready');empty.style.display='none';meta.textContent=`Latent step ${int(f.diffusion_step,index+1)} · t=${num(f.timestep).toFixed(0)} · 4×${int(f.latent_width)}×${int(f.latent_height)}`;}
"""
    new = """  let selectedLatentChannel=0;
  function latentChannelStat(frame,c){const s=arr(frame.channel_stats),o=c*5;return {min:num(s[o]),max:num(s[o+1]),mean:num(s[o+2]),std:num(s[o+3]),l2:num(s[o+4])};}
  function renderLatentInspector(s,force=false){
    const frames=arr(s.latent_maps);if(!force&&frames.length===lastLatentCount)return;lastLatentCount=frames.length;$('latent-badge').textContent=`${frames.length} 帧`;const scrub=$('latent-scrubber');scrub.max=String(Math.max(0,frames.length-1));if(selectedLatent<0||selectedLatent>=frames.length)selectedLatent=frames.length?frames.length-1:-1;scrub.value=String(Math.max(0,selectedLatent));
    const meta=$('latent-meta'),overview=$('latent-main-image'),empty=$('latent-empty'),grid=$('latent-channel-grid'),statsBox=$('latent-channel-stats'),histBox=$('latent-histogram'),corrBox=$('latent-correlation'),compare=$('latent-compare');grid.replaceChildren();statsBox.replaceChildren();histBox.replaceChildren();corrBox.replaceChildren();compare.replaceChildren();
    if(!frames.length||selectedLatent<0){overview.classList.remove('ready');overview.removeAttribute('src');empty.style.display='block';meta.textContent='—';return;}
    const frame=frames[clamp(selectedLatent,0,frames.length-1)],src=imageSrc(frame);overview.src=src;overview.classList.add('ready');empty.style.display='none';meta.textContent=`Latent step ${int(frame.diffusion_step,selectedLatent+1)}/${int(frame.diffusion_total)} · t=${num(frame.timestep).toFixed(0)} · 4×${int(frame.latent_width)}×${int(frame.latent_height)}`;
    for(let c=0;c<4;c++){const card=document.createElement('button');card.className='latent-channel'+(c===selectedLatentChannel?' active':'');const crop=document.createElement('div');crop.className='latent-channel-crop';crop.style.backgroundImage=`url(${src})`;crop.style.backgroundSize='200% 200%';crop.style.backgroundPosition=`${c%2?100:0}% ${c>1?100:0}%`;const label=document.createElement('b');label.textContent=`C${c}`;card.append(crop,label);card.addEventListener('click',()=>{selectedLatentChannel=c;renderLatentInspector(s,true);});grid.appendChild(card);}
    const st=latentChannelStat(frame,selectedLatentChannel);statsBox.replaceChildren(metric(`C${selectedLatentChannel} min`,st.min.toFixed(5)),metric('max',st.max.toFixed(5)),metric('mean',st.mean.toFixed(5)),metric('std',st.std.toFixed(5)),metric('L2',st.l2.toFixed(2)));
    const hist=arr(frame.channel_histograms).slice(selectedLatentChannel*32,(selectedLatentChannel+1)*32),hmax=Math.max(...hist.map(num),1e-12);hist.forEach((v,i)=>{const bar=document.createElement('div');bar.className='latent-hist-bar';bar.style.height=`${clamp(num(v)/hmax*100,0,100)}%`;bar.title=`bin ${i}: ${num(v).toFixed(4)}`;histBox.appendChild(bar);});
    const corr=arr(frame.channel_correlation);for(let r=0;r<4;r++)for(let c=0;c<4;c++){const cell=document.createElement('div');cell.className='latent-corr-cell';cell.textContent=num(corr[r*4+c]).toFixed(3);cell.title=`C${r} ↔ C${c}`;corrBox.appendChild(cell);}
    const previous=frames[Math.max(0,selectedLatent-1)],final=frames[frames.length-1],p=latentChannelStat(previous,selectedLatentChannel),f=latentChannelStat(final,selectedLatentChannel);
    // previous / current / final: compare the selected channel across time without another model pass.
    compare.replaceChildren(metric('previous',`μ ${p.mean.toFixed(4)} · σ ${p.std.toFixed(4)}`),metric('current',`μ ${st.mean.toFixed(4)} · σ ${st.std.toFixed(4)}`),metric('final',`μ ${f.mean.toFixed(4)} · σ ${f.std.toFixed(4)}`));
  }
"""
    text = replace_once(text, old, new, "latent inspector renderer")
    old_state = """  function renderLatentState(s,force=false){const latents=arr(s.latent_maps);if(force||latents.length!==lastLatentCount){lastLatentCount=latents.length;$('latent-badge').textContent=`${latents.length} 帧`;const scrub=$('latent-scrubber');scrub.max=String(Math.max(0,latents.length-1));selectedLatent=latents.length?latents.length-1:-1;scrub.value=String(Math.max(0,selectedLatent));showLatentFrame(latents,selectedLatent);}}
"""
    text = replace_once(text, old_state, "", "remove old latent renderer")
    text = replace_once(
        text,
        "  $('latent-scrubber').addEventListener('input',(e)=>{if(!pendingSnapshot)return;selectedLatent=int(e.target.value);showLatentFrame(arr(pendingSnapshot.latent_maps),selectedLatent);});\n",
        "  $('latent-scrubber').addEventListener('input',(e)=>{if(!pendingSnapshot)return;selectedLatent=int(e.target.value);renderLatentInspector(pendingSnapshot,true);});\n",
        "latent scrub inspector",
    )
    text = replace_once(
        text,
        "renderDecodedPreviews(s,force);renderLatentState(s,force);",
        "renderDecodedPreviews(s,force);renderLatentInspector(s,force);",
        "active latent inspector",
    )
    path.write_text(text, encoding="utf-8")


def patch_css(root: Path) -> None:
    path = root / "app/src/main/assets/s24u_microscope/microscope.css"
    text = path.read_text(encoding="utf-8")
    text += '''
/* H6R3 Latent State Inspector */
.latent-channel-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin:14px 0}.latent-channel{border:1px solid var(--line);border-radius:20px;padding:10px;background:var(--surface);text-align:left}.latent-channel.active{outline:3px solid color-mix(in srgb,var(--primary) 55%,transparent)}.latent-channel-crop{width:100%;aspect-ratio:1/1;border-radius:14px;background-repeat:no-repeat}.latent-channel b{display:block;padding:8px 2px 0}.latent-histogram{height:130px;display:flex;align-items:flex-end;gap:2px;padding:12px 4px;border-radius:18px;background:var(--surface)}.latent-hist-bar{flex:1;min-height:1px;background:var(--primary);border-radius:3px 3px 0 0}.latent-correlation{display:grid;grid-template-columns:repeat(4,1fr);gap:6px}.latent-corr-cell{padding:12px 4px;text-align:center;border-radius:12px;background:var(--surface);font-variant-numeric:tabular-nums}.section-head.minor{margin-top:22px}.section-head.minor h3{margin:4px 0 0}
'''
    path.write_text(text, encoding="utf-8")


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: patch_h6_v9_latent_ui.py <h6r3-task4-root>", file=sys.stderr)
        return 2
    root = Path(sys.argv[1]).resolve()
    patch_html(root)
    patch_js(root)
    patch_css(root)
    print("S24U_IMAGE_HARNESS_H6R3_LATENT_UI_APPLIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
