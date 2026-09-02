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
  let selectedPreview = -1;
  let selectedLatent = -1;

  const phaseCopy = {
    starting:'正在启动本地推理后端。', prompt:'Tokenizer 正在切分真实输入。', clip:'CLIP 正在把 token 编码为条件向量。',
    unet_step:'UNet 正在预测当前 step 的噪声。', scheduler_step:'Scheduler 正在把 zₜ 更新为 zₜ₋₁。',
    latent_map:'已捕捉 scheduler 更新后的真实 4 通道 latent。', vae_decode:'VAE 正在解码最终图像。',
    complete:'本次生成完成。', error:'本次生成出现错误。', idle:'等待一次真实生成。'
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
    const order = {prompt:0,clip:1,unet_step:2,scheduler_step:3,latent_map:3,vae_decode:4,complete:5};
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

  function formula(symbolic,sub,meaning){const d=document.createElement('div');d.className='formula';d.innerHTML=`<div class="symbolic"></div><div class="substitution"></div><div class="meaning"></div>`;d.children[0].textContent=symbolic;d.children[1].textContent=sub;d.children[2].textContent=meaning;return d;}
  function renderMechanism(s){const k=Math.max(arr(s.positive_chunk_tokens).length,arr(s.negative_chunk_tokens).length,1),hidden=int(s.hidden_dim),step=int(s.diffusion_step),total=int(s.diffusion_total),cfg=num(s.cfg,1);$('formula-list').replaceChildren(
    formula('K = min(Kmax, ceil(Ncontent / 75))',`Ncontent=${int(s.positive_input_tokens)}, K=${k}`, '每块固定 77 slots，其中最多 75 个内容 token。'),
    formula('Cₖ = CLIP(Tₖ),  Cₖ ∈ R^(77×hidden)',`77 × ${hidden||'hidden'} · K=${k}`,'每个 chunk 独立形成条件向量。'),
    formula('ε̄ₜ = (1/K) Σₖ εₜ⁽ᵏ⁾',`step ${step}/${total||'—'} · CFG=${cfg}`,'多 chunk 的真实 UNet 预测在 native 层取均值。'),
    formula('zₜ₋₁ = Scheduler(zₜ, ε̄ₜ, t)',`t=${num(s.timestep).toFixed(2)} · seen=${Boolean(s.scheduler_seen)}`,'Scheduler 更新 latent；下面的 latent 通道图就是这个内部状态。')
  );
    const grid=$('tensor-grid');grid.replaceChildren();[['CLIP seq',int(s.seq_len)||'—'],['Hidden',hidden||'—'],['Latent',int(s.latent_width)?`${int(s.latent_width)}×${int(s.latent_height)}`:'—'],['Chunks',k],['UNet',s.unet_seen?'YES':'NO'],['Scheduler',s.scheduler_seen?'YES':'NO']].forEach(([a,b])=>{const d=document.createElement('div');d.className='tensor-item';d.innerHTML='<span></span><strong></strong>';d.children[0].textContent=a;d.children[1].textContent=String(b);grid.appendChild(d);});
  }
  function renderExpert(s){$('positive-token-ids').textContent=arr(s.positive_token_ids).join(' ')||'—';$('negative-token-ids').textContent=arr(s.negative_token_ids).join(' ')||'—';$('raw-events').textContent=arr(s.events).slice(-40).map(e=>`+${int(e.elapsed_ms)}ms ${txt(e.phase)} ${int(e.diffusion_step)}/${int(e.diffusion_total)} dur=${int(e.duration_ms)}ms`).join('\n')||'等待真实 trace…';}

  function renderActive(s,force=false){ updateSummary(s); if(activePanel==='overview'){pipelineState(s);renderBudget(s);renderTimeline(s,force);} else if(activePanel==='process'){renderProcess(s,force);} else if(activePanel==='mechanism'){renderMechanism(s);} else if(activePanel==='expert'){renderExpert(s);} }
  function flush(){rafId=0;if(!pendingSnapshot)return;renderActive(pendingSnapshot,false);}
  window.S24UMicroscope={update(snapshot){pendingSnapshot=snapshot||{};if(!rafId)rafId=requestAnimationFrame(flush);}};
})();
