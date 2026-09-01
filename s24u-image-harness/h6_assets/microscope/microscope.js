(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const int = (v,d=0) => Number.isFinite(Number(v)) ? Math.trunc(Number(v)) : d;
  const num = (v,d=0) => Number.isFinite(Number(v)) ? Number(v) : d;
  const arr = (v) => Array.isArray(v) ? v : [];
  const txt = (v,d='—') => (v === undefined || v === null || v === '') ? d : String(v);
  const clamp = (v,a,b) => Math.max(a,Math.min(b,v));

  let pendingSnapshot = null;
  let rafId = 0;
  let activePanel = 'overview';
  let lastEventCount = -1;
  let lastBudgetKey = '';
  let lastPreviewCount = -1;
  let lastLatentCount = -1;
  let lastInfluenceCount = -1;
  let selectedPreview = -1;
  let selectedLatent = -1;
  let selectedInfluenceStep = -1;
  let selectedInfluenceChunk = 0;

  const phaseCopy = {
    starting:'正在启动本地推理后端。', prompt:'Tokenizer 正在切分真实输入。', clip:'CLIP 正在把 token 编码为条件向量。',
    unet_step:'UNet 正在预测当前 step 的噪声。', conditioning_influence:'正在比较各 chunk prediction 与最终 fused prediction。',
    scheduler_step:'Scheduler 正在把 zₜ 更新为 zₜ₋₁。', latent_map:'已捕捉 scheduler 更新后的真实 4 通道 latent。',
    vae_decode:'VAE 正在解码最终图像。', complete:'本次生成完成。', error:'本次生成出现错误。', idle:'等待一次真实生成。'
  };

  document.querySelectorAll('.tab').forEach((button) => button.addEventListener('click', () => {
    activePanel = button.dataset.tab;
    document.querySelectorAll('.tab').forEach((b) => b.classList.toggle('active', b === button));
    document.querySelectorAll('.panel').forEach((p) => p.classList.toggle('active', p.dataset.panel === activePanel));
    if (pendingSnapshot) renderActive(pendingSnapshot, true);
  }));

  function updateSummary(s) {
    $('phase-pill').textContent = txt(s.phase,'WAIT').toUpperCase();
    $('stage-explain').textContent = phaseCopy[s.phase] || `当前阶段：${txt(s.phase)}`;
    $('progress-value').textContent = `${Math.round(clamp(num(s.trace_progress)*100,0,100))}%`;
    $('backend-value').textContent = txt(s.backend,'NPU/QNN');
    $('resolution-value').textContent = int(s.width)>0 ? `${int(s.width)}×${int(s.height)}` : '—';
    $('total-value').textContent = int(s.total_ms)>0 ? `${int(s.total_ms)} ms` : '—';
  }

  function pipelineState(s) {
    const order = {prompt:0,clip:1,unet_step:2,conditioning_influence:2,scheduler_step:3,latent_map:3,vae_decode:4,complete:5};
    const phase = s.phase || 'idle'; const idx = order[phase] ?? -1;
    const nodeIndex = {prompt:0,token:0,clip:1,unet:2,scheduler:3,vae:4,image:5};
    document.querySelectorAll('.node').forEach((node) => {
      node.classList.remove('active','done'); const target=nodeIndex[node.dataset.node];
      if (phase==='complete') { node.classList.add(target===5?'active':'done'); return; }
      if (idx<0) return; if (target<idx) node.classList.add('done'); else if (target===idx) node.classList.add('active');
    });
    const step=int(s.diffusion_step), total=int(s.diffusion_total);
    $('step-badge').textContent = total>0 ? `step ${step}/${total} · t=${num(s.timestep).toFixed(0)}` : '等待 step';
  }

  function metric(label,value){ const d=document.createElement('div'); const a=document.createElement('span');a.textContent=label;const b=document.createElement('strong');b.textContent=value;d.append(a,b);return d; }
  function renderBudget(s) {
    const key=[s.positive_input_tokens,s.positive_effective_tokens,s.positive_truncated_tokens,s.negative_input_tokens,s.negative_effective_tokens,s.negative_truncated_tokens,arr(s.positive_chunk_tokens).join(','),arr(s.negative_chunk_tokens).join(',')].join('|');
    if (key===lastBudgetKey) return; lastBudgetKey=key;
    $('budget-summary').replaceChildren(
      metric('Positive 输入 / 参与',`${int(s.positive_input_tokens)} / ${int(s.positive_effective_tokens)}`),
      metric('Negative 输入 / 参与',`${int(s.negative_input_tokens)} / ${int(s.negative_effective_tokens)}`),
      metric('Chunk 预算',`${int(s.max_chunks,8)} × 75`)
    );
    const trunc=int(s.positive_truncated_tokens)+int(s.negative_truncated_tokens), w=$('truncation-warning');
    w.classList.toggle('hidden',trunc<=0); w.textContent=trunc>0?`有 ${trunc} 个 token 未进入推理：Positive ${int(s.positive_truncated_tokens)}，Negative ${int(s.negative_truncated_tokens)}。`:'';
    const box=$('chunk-summary'); box.replaceChildren();
    [['Positive',arr(s.positive_chunk_tokens),arr(s.positive_chunks)],['Negative',arr(s.negative_chunk_tokens),arr(s.negative_chunks)]].forEach(([name,counts,texts])=>{
      const row=document.createElement('div');row.className='chunk-line';const strong=document.createElement('strong');strong.textContent=`${name} · ${counts.length||1} chunk`;
      const span=document.createElement('span');span.textContent=counts.length?counts.map((c,i)=>`#${i+1}:${c} ${txt(texts[i],'')}`).join('  ·  '):(name==='Negative'?'空 negative prompt':'等待 tokenizer');row.append(strong,span);box.appendChild(row);
    });
  }

  function renderTimeline(s, force=false) {
    const events=arr(s.events).filter(e=>['prompt','clip','unet_step','scheduler_step','vae_decode','complete'].includes(e.phase));
    if (!force && events.length===lastEventCount) return; lastEventCount=events.length;
    const box=$('timeline');box.replaceChildren(); const total=Math.max(int(s.total_ms),...events.map(e=>int(e.elapsed_ms)),1); $('timeline-total').textContent=`${total} ms`;
    events.slice(-28).forEach(e=>{ const row=document.createElement('div');row.className=`timeline-row ${e.phase}`; const label=document.createElement('div');label.className='timeline-label';
      label.textContent=e.phase==='unet_step'?`UNet ${int(e.diffusion_step)}/${int(e.diffusion_total)}`:e.phase==='scheduler_step'?`Sched ${int(e.diffusion_step)}/${int(e.diffusion_total)}`:e.phase;
      const track=document.createElement('div');track.className='timeline-track';const bar=document.createElement('div');bar.className='timeline-bar'; const elapsed=int(e.elapsed_ms),dur=Math.max(int(e.duration_ms),0),start=Math.max(0,elapsed-dur);bar.style.left=`${clamp(start/total*100,0,100)}%`;bar.style.width=`${Math.max(.35,Math.min(dur/total*100,100))}%`;track.appendChild(bar);
      const d=document.createElement('div');d.className='timeline-duration';d.textContent=`${dur}ms`;row.append(label,track,d);box.appendChild(row); });
  }

  function imageSrc(frame){ const format=txt(frame.format,'jpeg').toLowerCase(); return `data:image/${format};base64,${frame.image_base64||''}`; }
  function showFrame(kind, frames, index) {
    const process=kind==='process'; const image=$(process?'process-main-image':'latent-main-image'); const empty=$(process?'process-empty':'latent-empty'); const meta=$(process?'process-meta':'latent-meta');
    if (!frames.length || index<0) { image.classList.remove('ready'); image.removeAttribute('src'); empty.style.display='block'; meta.textContent='—'; return; }
    const f=frames[clamp(index,0,frames.length-1)]; image.src=imageSrc(f);image.classList.add('ready');empty.style.display='none';
    meta.textContent=process?`真实 VAE 帧 ${int(f.preview_index,index+1)} · progress ${int(f.step)}/${int(f.total_steps)} · ${txt(f.format,'jpeg').toUpperCase()}`:`Latent step ${int(f.diffusion_step,index+1)} · t=${num(f.timestep).toFixed(0)} · 4×${int(f.latent_width)}×${int(f.latent_height)}`;
  }
  function renderProcess(s, force=false) {
    const previews=arr(s.process_previews), latents=arr(s.latent_maps);
    if (force || previews.length!==lastPreviewCount) {
      lastPreviewCount=previews.length; $('preview-badge').textContent=`${previews.length} 帧`; const scrub=$('process-scrubber');scrub.max=String(Math.max(0,previews.length-1)); selectedPreview=previews.length?previews.length-1:-1;scrub.value=String(Math.max(0,selectedPreview));
      const thumbs=$('process-thumbs');thumbs.replaceChildren();previews.forEach((f,i)=>{const b=document.createElement('button');b.className='thumb'+(i===selectedPreview?' active':'');const img=document.createElement('img');img.src=imageSrc(f);img.alt=`step ${i+1}`;b.appendChild(img);b.addEventListener('click',()=>{selectedPreview=i;scrub.value=String(i);showFrame('process',previews,i);thumbs.querySelectorAll('.thumb').forEach((x,j)=>x.classList.toggle('active',j===i));});thumbs.appendChild(b);});
      showFrame('process',previews,selectedPreview);
    }
    if (force || latents.length!==lastLatentCount) { lastLatentCount=latents.length;$('latent-badge').textContent=`${latents.length} 帧`;const scrub=$('latent-scrubber');scrub.max=String(Math.max(0,latents.length-1));selectedLatent=latents.length?latents.length-1:-1;scrub.value=String(Math.max(0,selectedLatent));showFrame('latent',latents,selectedLatent); }
  }
  $('process-scrubber').addEventListener('input',(e)=>{ if(!pendingSnapshot)return; selectedPreview=int(e.target.value);showFrame('process',arr(pendingSnapshot.process_previews),selectedPreview); });
  $('latent-scrubber').addEventListener('input',(e)=>{ if(!pendingSnapshot)return; selectedLatent=int(e.target.value);showFrame('latent',arr(pendingSnapshot.latent_maps),selectedLatent); });

  function influenceSteps(samples){return [...new Set(samples.map(x=>int(x.diffusion_step)).filter(x=>x>0))].sort((a,b)=>a-b);}
  function chunkText(s,index){
    const pos=txt(arr(s.positive_chunks)[index],'(empty positive)');
    const neg=txt(arr(s.negative_chunks)[index],'(empty negative)');
    return {pos,neg};
  }
  function showInfluenceSample(s,sample,stepSamples){
    const image=$('influence-main-image'),empty=$('influence-empty'),meta=$('influence-meta');
    if(!sample){image.classList.remove('ready');image.removeAttribute('src');empty.style.display='block';meta.textContent='—';$('influence-metrics').replaceChildren();$('influence-bars').replaceChildren();return;}
    if(sample.image_base64){image.src=`data:image/jpeg;base64,${sample.image_base64}`;image.classList.add('ready');empty.style.display='none';}else{image.classList.remove('ready');image.removeAttribute('src');empty.style.display='block';}
    $('influence-metrics').replaceChildren(
      metric('Mean |εₖ|',num(sample.mean_abs).toFixed(5)),
      metric('L2(εₖ)',num(sample.l2).toFixed(4)),
      metric('cos(εₖ, ε̄)',num(sample.fused_cosine).toFixed(5)),
      metric('L2(εₖ−ε̄)',num(sample.delta_l2).toFixed(4))
    );
    const texts=chunkText(s,int(sample.chunk_index));
    meta.textContent=`step ${int(sample.diffusion_step)}/${int(sample.diffusion_total)} · chunk ${int(sample.chunk_index)+1}/${int(sample.chunk_count)} · t=${num(sample.timestep).toFixed(0)} · POS: ${texts.pos} · NEG: ${texts.neg}`;
    const max=Math.max(...stepSamples.map(x=>num(x.delta_l2)),1e-12);const bars=$('influence-bars');bars.replaceChildren();
    stepSamples.forEach(x=>{const row=document.createElement('div');row.className='influence-bar-row';const label=document.createElement('div');label.className='influence-bar-label';label.textContent=`Chunk ${int(x.chunk_index)+1}`;const track=document.createElement('div');track.className='influence-bar-track';const fill=document.createElement('div');fill.className='influence-bar-fill';fill.style.width=`${clamp(num(x.delta_l2)/max*100,0,100)}%`;track.appendChild(fill);const value=document.createElement('div');value.className='influence-bar-value';value.textContent=num(x.delta_l2).toFixed(3);row.append(label,track,value);bars.appendChild(row);});
  }
  function renderInfluence(s,force=false){
    const samples=arr(s.influence_samples);if(!force&&samples.length===lastInfluenceCount)return;lastInfluenceCount=samples.length;$('influence-badge').textContent=`${samples.length} 样本`;
    const steps=influenceSteps(samples),scrub=$('influence-step-scrubber');scrub.max=String(Math.max(0,steps.length-1));
    if(!steps.length){selectedInfluenceStep=-1;selectedInfluenceChunk=0;scrub.value='0';$('influence-step-label').textContent='—';$('influence-chunks').replaceChildren();showInfluenceSample(s,null,[]);return;}
    if(!steps.includes(selectedInfluenceStep))selectedInfluenceStep=steps[steps.length-1];const stepIndex=Math.max(0,steps.indexOf(selectedInfluenceStep));scrub.value=String(stepIndex);$('influence-step-label').textContent=`${selectedInfluenceStep}/${int(samples[samples.length-1].diffusion_total)}`;
    const stepSamples=samples.filter(x=>int(x.diffusion_step)===selectedInfluenceStep).sort((a,b)=>int(a.chunk_index)-int(b.chunk_index));
    if(!stepSamples.some(x=>int(x.chunk_index)===selectedInfluenceChunk))selectedInfluenceChunk=stepSamples.length?int(stepSamples[0].chunk_index):0;
    const chunks=$('influence-chunks');chunks.replaceChildren();stepSamples.forEach(sample=>{const idx=int(sample.chunk_index),texts=chunkText(s,idx),b=document.createElement('button');b.className='influence-chunk'+(idx===selectedInfluenceChunk?' active':'');const title=document.createElement('b');title.textContent=`Chunk ${idx+1} · ΔL2 ${num(sample.delta_l2).toFixed(3)}`;const body=document.createElement('span');body.textContent=`POS ${texts.pos} · NEG ${texts.neg}`;b.append(title,body);b.addEventListener('click',()=>{selectedInfluenceChunk=idx;renderInfluence(s,true);});chunks.appendChild(b);});
    const selected=stepSamples.find(x=>int(x.chunk_index)===selectedInfluenceChunk)||stepSamples[0];showInfluenceSample(s,selected,stepSamples);
  }
  $('influence-step-scrubber').addEventListener('input',(e)=>{if(!pendingSnapshot)return;const steps=influenceSteps(arr(pendingSnapshot.influence_samples));selectedInfluenceStep=steps[clamp(int(e.target.value),0,Math.max(0,steps.length-1))]||-1;selectedInfluenceChunk=0;renderInfluence(pendingSnapshot,true);});

  function formula(symbolic,sub,meaning){const d=document.createElement('div');d.className='formula';d.innerHTML=`<div class="symbolic"></div><div class="substitution"></div><div class="meaning"></div>`;d.children[0].textContent=symbolic;d.children[1].textContent=sub;d.children[2].textContent=meaning;return d;}
  function renderMechanism(s){const k=Math.max(arr(s.positive_chunk_tokens).length,arr(s.negative_chunk_tokens).length,1),hidden=int(s.hidden_dim),step=int(s.diffusion_step),total=int(s.diffusion_total),cfg=num(s.cfg,1);$('formula-list').replaceChildren(
    formula('K = min(Kmax, ceil(Ncontent / 75))',`Ncontent=${int(s.positive_input_tokens)}, K=${k}`, '每块固定 77 slots，其中最多 75 个内容 token。'),
    formula('Cₖ = CLIP(Tₖ),  Cₖ ∈ R^(77×hidden)',`77 × ${hidden||'hidden'} · K=${k}`,'每个 chunk 独立形成条件向量。'),
    formula('ε̄ₜ = (1/K) Σₖ εₜ⁽ᵏ⁾',`step ${step}/${total||'—'} · CFG=${cfg}`,'多 chunk 的真实 UNet 预测在 native 层取均值。'),
    formula('Iₖ = |εₜ⁽ᵏ⁾ − ε̄ₜ|',`H6 influence samples=${arr(s.influence_samples).length}`,'H6 展示的是 chunk prediction 相对 fused prediction 的差异，不是 cross-attention。'),
    formula('zₜ₋₁ = Scheduler(zₜ, ε̄ₜ, t)',`t=${num(s.timestep).toFixed(2)} · seen=${Boolean(s.scheduler_seen)}`,'Scheduler 使用的 ε̄ₜ 与 H2 完全相同。')
  );
    const grid=$('tensor-grid');grid.replaceChildren();[['CLIP seq',int(s.seq_len)||'—'],['Hidden',hidden||'—'],['Latent',int(s.latent_width)?`${int(s.latent_width)}×${int(s.latent_height)}`:'—'],['Chunks',k],['Influence',arr(s.influence_samples).length],['Scheduler',s.scheduler_seen?'YES':'NO']].forEach(([a,b])=>{const d=document.createElement('div');d.className='tensor-item';d.innerHTML='<span></span><strong></strong>';d.children[0].textContent=a;d.children[1].textContent=String(b);grid.appendChild(d);});
  }
  function renderExpert(s){$('positive-token-ids').textContent=arr(s.positive_token_ids).join(' ')||'—';$('negative-token-ids').textContent=arr(s.negative_token_ids).join(' ')||'—';$('raw-events').textContent=arr(s.events).slice(-40).map(e=>`+${int(e.elapsed_ms)}ms ${txt(e.phase)} ${int(e.diffusion_step)}/${int(e.diffusion_total)} dur=${int(e.duration_ms)}ms`).join('\n')||'等待真实 trace…';}

  function renderActive(s,force=false){ updateSummary(s); if(activePanel==='overview'){pipelineState(s);renderBudget(s);renderTimeline(s,force);} else if(activePanel==='process'){renderProcess(s,force);} else if(activePanel==='influence'){renderInfluence(s,force);} else if(activePanel==='mechanism'){renderMechanism(s);} else if(activePanel==='expert'){renderExpert(s);} }
  function flush(){rafId=0;if(!pendingSnapshot)return;renderActive(pendingSnapshot,false);}
  window.S24UMicroscope={
    update(snapshot){
      pendingSnapshot=Object.assign({},pendingSnapshot||{},snapshot||{});
      if(!rafId)rafId=requestAnimationFrame(flush);
    },
    addMedia(media){
      pendingSnapshot=Object.assign({},pendingSnapshot||{});
      if(media&&media.process_preview){
        const frame=media.process_preview,frames=arr(pendingSnapshot.process_previews).slice(),key=int(frame.preview_index,frames.length+1),idx=frames.findIndex(x=>int(x.preview_index)===key);
        if(idx>=0)frames[idx]=frame;else frames.push(frame);pendingSnapshot.process_previews=frames.slice(-8);
      }
      if(media&&media.latent_map){
        const frame=media.latent_map,frames=arr(pendingSnapshot.latent_maps).slice(),key=int(frame.diffusion_step,frames.length+1),idx=frames.findIndex(x=>int(x.diffusion_step)===key);
        if(idx>=0)frames[idx]=frame;else frames.push(frame);pendingSnapshot.latent_maps=frames.slice(-8);
      }
      if(media&&media.influence_sample){
        const sample=media.influence_sample,samples=arr(pendingSnapshot.influence_samples).slice(),key=`${int(sample.diffusion_step)}:${int(sample.chunk_index)}`,idx=samples.findIndex(x=>`${int(x.diffusion_step)}:${int(x.chunk_index)}`===key);
        if(idx>=0)samples[idx]=sample;else samples.push(sample);pendingSnapshot.influence_samples=samples.slice(-32);
      }
      if(!rafId)rafId=requestAnimationFrame(flush);
    }
  };
})();
