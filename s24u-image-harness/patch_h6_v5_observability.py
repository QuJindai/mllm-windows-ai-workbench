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
    text = replace_once(text, "versionCode = 7407", "versionCode = 7408", "H6R2 versionCode")
    text = replace_once(
        text,
        'versionName = "2.8.1-s24u-h6r1"',
        'versionName = "2.8.1-s24u-h6r2"',
        "H6R2 versionName",
    )
    path.write_text(text, encoding="utf-8")


def patch_screen(root: Path) -> None:
    path = root / "app/src/main/java/io/github/xororz/localdream/ui/screens/ModelRunScreen.kt"
    text = path.read_text(encoding="utf-8")
    marker = '            put("h6r1_marker", "S24U_H6R1_GESTURE_ARBITRATION")\n'
    text = replace_once(
        text,
        marker,
        marker + '            put("h6r2_marker", "S24U_H6R2_OBSERVABILITY_FALLBACK")\n',
        "H6R2 compiled DEX marker",
    )
    path.write_text(text, encoding="utf-8")


def patch_html(root: Path) -> None:
    path = root / "app/src/main/assets/s24u_microscope/index.html"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '<span class="kicker">REAL VAE PREVIEW</span><h2>逐 step 生成过程</h2>',
        '<span class="kicker">PROCESS EVIDENCE</span><h2>逐 step 生成过程</h2>',
        "H6R2 process evidence heading",
    )
    text = replace_once(
        text,
        '这些图来自 Local Dream 原生 <code>renderPreview()</code>：当前 latent 经过真实 VAE decode，不是 UI 模拟动画。',
        '优先显示 Local Dream 原生 <code>renderPreview()</code> 的真实 VAE 帧；当 SDXL QNN 低内存模式禁止逐 step VAE decode 时，自动回退显示同一步真实 scheduler latent，不增加额外模型推理。',
        "H6R2 truthful process fallback copy",
    )
    text = replace_once(
        text,
        '开始生成后，这里会保留真实过程帧。',
        '等待真实过程证据；低内存模式有 latent 时会自动回退显示。',
        "H6R2 process empty copy",
    )
    text = replace_once(
        text,
        '<div class="section-head"><div><span class="kicker">ATTRIBUTION</span><h2>词语 → 图像区域</h2></div></div>',
        '<div class="section-head"><div><span class="kicker">ATTRIBUTION · CAPABILITY</span><h2>词语 → 图像区域 · 能力状态</h2></div></div>',
        "H6R2 attribution capability heading",
    )
    text = replace_once(
        text,
        '<div class="attention-state"><strong>Cross-attention 未采集</strong><p>当前 QNN 编译图没有把 cross-attention 中间 tensor 声明为图输出。H6 的 conditioning influence 只说明各 chunk prediction 与 fused prediction 的差异，不能冒充 token-level attention。</p></div>',
        '<div class="attention-state"><strong>当前不可观测：Cross-attention 未导出</strong><p>这是当前 QNN 编译图的能力缺口，不是页面加载失败。编译图没有把 cross-attention 中间 tensor 声明为图输出；H6 的 conditioning influence 只说明各 chunk prediction 与 fused prediction 的差异，不能冒充 token-level attention。</p></div>',
        "H6R2 attribution capability explanation",
    )
    path.write_text(text, encoding="utf-8")


def patch_js(root: Path) -> None:
    path = root / "app/src/main/assets/s24u_microscope/microscope.js"
    text = path.read_text(encoding="utf-8")

    old_show = """    meta.textContent=process?`真实 VAE 帧 ${int(f.preview_index,index+1)} · progress ${int(f.step)}/${int(f.total_steps)} · ${txt(f.format,'jpeg').toUpperCase()}`:`Latent step ${int(f.diffusion_step,index+1)} · t=${num(f.timestep).toFixed(0)} · 4×${int(f.latent_width)}×${int(f.latent_height)}`;
"""
    new_show = """    if(process){
      const latentFallback=int(f.preview_index,0)<=0 && int(f.diffusion_step,0)>0;
      meta.textContent=latentFallback
        ? `LATENT FALLBACK · step ${int(f.diffusion_step,index+1)}/${int(f.diffusion_total)} · t=${num(f.timestep).toFixed(0)} · 真实 scheduler latent · 非 VAE decode`
        : `真实 VAE 帧 ${int(f.preview_index,index+1)} · progress ${int(f.step)}/${int(f.total_steps)} · ${txt(f.format,'jpeg').toUpperCase()}`;
    }else{
      meta.textContent=`Latent step ${int(f.diffusion_step,index+1)} · t=${num(f.timestep).toFixed(0)} · 4×${int(f.latent_width)}×${int(f.latent_height)}`;
    }
"""
    text = replace_once(text, old_show, new_show, "H6R2 process frame semantics")

    old_process = """    const previews=arr(s.process_previews), latents=arr(s.latent_maps);
    if (force || previews.length!==lastPreviewCount) {
      lastPreviewCount=previews.length; $('preview-badge').textContent=`${previews.length} 帧`; const scrub=$('process-scrubber');scrub.max=String(Math.max(0,previews.length-1)); selectedPreview=previews.length?previews.length-1:-1;scrub.value=String(Math.max(0,selectedPreview));
      const thumbs=$('process-thumbs');thumbs.replaceChildren();previews.forEach((f,i)=>{const b=document.createElement('button');b.className='thumb'+(i===selectedPreview?' active':'');const img=document.createElement('img');img.src=imageSrc(f);img.alt=`step ${i+1}`;b.appendChild(img);b.addEventListener('click',()=>{selectedPreview=i;scrub.value=String(i);showFrame('process',previews,i);thumbs.querySelectorAll('.thumb').forEach((x,j)=>x.classList.toggle('active',j===i));});thumbs.appendChild(b);});
      showFrame('process',previews,selectedPreview);
    }
"""
    new_process = """    const previews=arr(s.process_previews), latents=arr(s.latent_maps);
    const usingLatentFallback=previews.length===0 && latents.length>0;
    const processFrames=usingLatentFallback?latents:previews;
    const processRevision=previews.length*1000+latents.length;
    if (force || processRevision!==lastPreviewCount) {
      lastPreviewCount=processRevision;
      $('preview-badge').textContent=usingLatentFallback?`${processFrames.length} 状态 · LATENT`:`${processFrames.length} 帧 · VAE`;
      $('process-empty').textContent=usingLatentFallback?'SDXL QNN 低内存模式未执行逐 step VAE decode；这里显示真实 scheduler latent。':'等待真实 VAE 过程帧。';
      const scrub=$('process-scrubber');scrub.max=String(Math.max(0,processFrames.length-1)); selectedPreview=processFrames.length?processFrames.length-1:-1;scrub.value=String(Math.max(0,selectedPreview));
      const thumbs=$('process-thumbs');thumbs.replaceChildren();processFrames.forEach((f,i)=>{const b=document.createElement('button');b.className='thumb'+(i===selectedPreview?' active':'');const img=document.createElement('img');img.src=imageSrc(f);img.alt=`step ${i+1}`;b.appendChild(img);b.addEventListener('click',()=>{selectedPreview=i;scrub.value=String(i);showFrame('process',processFrames,i);thumbs.querySelectorAll('.thumb').forEach((x,j)=>x.classList.toggle('active',j===i));});thumbs.appendChild(b);});
      showFrame('process',processFrames,selectedPreview);
    }
"""
    text = replace_once(text, old_process, new_process, "H6R2 lowram process fallback")

    old_scrub = """  $('process-scrubber').addEventListener('input',(e)=>{ if(!pendingSnapshot)return; selectedPreview=int(e.target.value);showFrame('process',arr(pendingSnapshot.process_previews),selectedPreview); });
"""
    new_scrub = """  $('process-scrubber').addEventListener('input',(e)=>{ if(!pendingSnapshot)return; selectedPreview=int(e.target.value);const previews=arr(pendingSnapshot.process_previews),latents=arr(pendingSnapshot.latent_maps);showFrame('process',previews.length?previews:latents,selectedPreview); });
"""
    text = replace_once(text, old_scrub, new_scrub, "H6R2 process scrub fallback")

    old_influence = """    if(sample.image_base64){image.src=`data:image/jpeg;base64,${sample.image_base64}`;image.classList.add('ready');empty.style.display='none';}else{image.classList.remove('ready');image.removeAttribute('src');empty.style.display='block';}
"""
    new_influence = """    const singleChunk=int(sample.chunk_count,1)===1;
    const zeroDelta=Math.abs(num(sample.delta_l2))<1e-8;
    if(singleChunk){
      image.classList.remove('ready');image.removeAttribute('src');empty.style.display='block';
      empty.textContent='单 Chunk 场景：ε̄ₜ = εₜ⁽¹⁾，因此 |εₜ⁽¹⁾−ε̄ₜ| = 0。这里不再显示没有信息量的全黑图。';
    }else if(zeroDelta){
      image.classList.remove('ready');image.removeAttribute('src');empty.style.display='block';
      empty.textContent='当前 Chunk prediction 与 fused prediction 的差异为 0，因此没有可显示的空间影响。';
    }else if(sample.image_base64){image.src=`data:image/jpeg;base64,${sample.image_base64}`;image.classList.add('ready');empty.style.display='none';}else{image.classList.remove('ready');image.removeAttribute('src');empty.style.display='block';empty.textContent='等待真实 conditioning influence 图…';}
"""
    text = replace_once(text, old_influence, new_influence, "H6R2 single-chunk zero influence explanation")
    path.write_text(text, encoding="utf-8")


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: patch_h6_v5_observability.py <h6r1-patched-local-dream-root>", file=sys.stderr)
        return 2
    root = Path(sys.argv[1]).resolve()
    patch_gradle(root)
    patch_screen(root)
    patch_html(root)
    patch_js(root)
    print("S24U_IMAGE_HARNESS_H6R2_OBSERVABILITY_FALLBACK_APPLIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
