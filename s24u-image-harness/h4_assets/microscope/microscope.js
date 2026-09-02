(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, Number.isFinite(v) ? v : lo));
  const int = (v, d = 0) => Number.isFinite(Number(v)) ? Math.trunc(Number(v)) : d;
  const num = (v, d = 0) => Number.isFinite(Number(v)) ? Number(v) : d;
  const arr = (v) => Array.isArray(v) ? v : [];
  const text = (v, d = '—') => (v === undefined || v === null || v === '') ? d : String(v);

  const phaseOrder = ['prompt', 'clip', 'unet_step', 'scheduler_step', 'vae_decode', 'complete'];
  const phaseCopy = {
    starting: '正在启动本地推理后端，准备 tokenizer、CLIP、UNet 与 VAE。',
    prompt: 'Tokenizer 正在把你的原始提示词切成固定 77-slot 的 CLIP 输入块；这里直接显示真实参与和被截断的 token。',
    clip: 'CLIP 正在把 token 序列编码为条件向量 Cₖ。多个 chunk 会得到多组条件向量。',
    unet_step: 'UNet 正在对当前 latent 预测噪声 εₜ。H4 会把每个真实 diffusion step 的耗时画到时间轴。',
    scheduler_step: 'Scheduler 正在根据噪声预测把 zₜ 更新为 zₜ₋₁；0 ms 也代表真实观察到，而不是 WAIT。',
    vae_decode: 'VAE 正在把最终 latent 解码到 RGB 图像空间。',
    complete: '本次端侧生成已完成；下面所有图、公式和时间轴均来自这一轮真实 trace。',
    error: '本次生成出现错误。专家证据区域保留已经收到的原始 trace，便于定位。',
    idle: '等待一次真实生成。',
  };

  function stageIndex(phase) {
    const i = phaseOrder.indexOf(phase);
    return i >= 0 ? i : -1;
  }

  function nodeStateFor(snapshot, node) {
    const phase = text(snapshot.phase, 'idle');
    const idx = stageIndex(phase);
    const complete = phase === 'complete';
    const map = {
      prompt: 0,
      token: 0,
      clip: 1,
      unet: 2,
      fusion: 2,
      scheduler: 3,
      latent: 3,
      vae: 4,
      image: 5,
    };
    const target = map[node];
    if (target === undefined || idx < 0) return '';
    if (complete && target <= 5) return node === 'image' ? 'active' : 'done';
    if (target < idx) return 'done';
    if (target === idx) return 'active';
    if (node === 'fusion' && snapshot.unet_seen && idx >= 2) return idx > 2 ? 'done' : 'active';
    return '';
  }

  function renderPipeline(snapshot) {
    ['prompt','token','clip','unet','fusion','scheduler','latent','vae','image'].forEach((name) => {
      const el = $(`node-${name}`);
      if (!el) return;
      el.classList.remove('active', 'done');
      const state = nodeStateFor(snapshot, name);
      if (state) el.classList.add(state);
    });
    const latent = $('latent-node-sub');
    if (latent) {
      const w = int(snapshot.latent_width);
      const h = int(snapshot.latent_height);
      latent.textContent = w > 0 && h > 0 ? `${w} × ${h}` : 'latent';
    }

    const total = int(snapshot.diffusion_total);
    const current = int(snapshot.diffusion_step);
    const strip = $('step-strip');
    strip.replaceChildren();
    if (total <= 0) {
      const chip = document.createElement('div');
      chip.className = 'step-chip';
      chip.textContent = '等待 diffusion step';
      strip.appendChild(chip);
      return;
    }
    for (let i = 1; i <= total; i += 1) {
      const chip = document.createElement('div');
      chip.className = 'step-chip';
      if (i < current || snapshot.phase === 'complete') chip.classList.add('done');
      if (i === current && snapshot.phase !== 'complete') chip.classList.add('active');
      const event = arr(snapshot.events).filter((e) => e.phase === 'unet_step' && int(e.diffusion_step) === i).at(-1);
      chip.textContent = event ? `${i}/${total} · ${int(event.duration_ms)}ms` : `${i}/${total}`;
      strip.appendChild(chip);
    }
  }

  function budget(snapshot, prefix) {
    return {
      input: int(snapshot[`${prefix}_input_tokens`]),
      effective: int(snapshot[`${prefix}_effective_tokens`]),
      truncated: int(snapshot[`${prefix}_truncated_tokens`]),
      chunks: arr(snapshot[`${prefix}_chunk_tokens`]),
      texts: arr(snapshot[`${prefix}_chunks`]),
    };
  }

  function metric(label, value) {
    const div = document.createElement('div');
    div.className = 'budget-metric';
    const span = document.createElement('span');
    span.textContent = label;
    const strong = document.createElement('strong');
    strong.textContent = value;
    div.append(span, strong);
    return div;
  }

  function slotStrip(contentCount) {
    const strip = document.createElement('div');
    strip.className = 'token-strip';
    const content = clamp(int(contentCount), 0, 75);
    for (let i = 0; i < 77; i += 1) {
      const slot = document.createElement('span');
      slot.className = 'token-slot';
      if (i === 0) slot.classList.add('bos');
      else if (i <= content) slot.classList.add('content');
      else if (i === content + 1) slot.classList.add('eos');
      else slot.classList.add('pad');
      slot.title = `slot ${i}`;
      strip.appendChild(slot);
    }
    return strip;
  }

  function renderChunkZone(zoneId, label, data) {
    const zone = $(zoneId);
    zone.replaceChildren();
    const title = document.createElement('div');
    title.className = 'chunk-group-title';
    const left = document.createElement('strong');
    left.textContent = label;
    const right = document.createElement('span');
    right.textContent = `${data.chunks.length || 0} chunk`;
    title.append(left, right);
    zone.appendChild(title);

    if (!data.chunks.length) {
      const empty = document.createElement('div');
      empty.className = 'chunk-text';
      empty.textContent = label === 'Negative' ? '空 negative prompt' : '等待 tokenizer trace…';
      zone.appendChild(empty);
      return;
    }

    data.chunks.forEach((count, index) => {
      const row = document.createElement('div');
      row.className = 'chunk-row';
      const chunkLabel = document.createElement('div');
      chunkLabel.className = 'chunk-label';
      chunkLabel.textContent = `#${index + 1} · ${int(count)}`;
      row.append(chunkLabel, slotStrip(count));
      const chunkText = document.createElement('div');
      chunkText.className = 'chunk-text';
      chunkText.textContent = text(data.texts[index], '');
      row.appendChild(chunkText);
      zone.appendChild(row);
    });
  }

  function renderTokenChunks(snapshot) {
    const pos = budget(snapshot, 'positive');
    const neg = budget(snapshot, 'negative');
    const maxChunks = int(snapshot.max_chunks, 8);
    const summary = $('budget-summary');
    summary.replaceChildren(
      metric('Positive 输入 / 参与', `${pos.input} / ${pos.effective}`),
      metric('Negative 输入 / 参与', `${neg.input} / ${neg.effective}`),
      metric('固定图预算', `${maxChunks} × 75 + BOS/EOS`),
    );

    const warning = $('truncation-warning');
    const trunc = pos.truncated + neg.truncated;
    if (trunc > 0) {
      warning.classList.remove('hidden');
      warning.textContent = `本次输入有 ${trunc} 个 token 没有进入实际条件推理：Positive 截断 ${pos.truncated}，Negative 截断 ${neg.truncated}。这里不会把被截断内容标成“已参与”。`;
    } else {
      warning.classList.add('hidden');
      warning.textContent = '';
    }

    renderChunkZone('positive-chunks', 'Positive', pos);
    renderChunkZone('negative-chunks', 'Negative', neg);
  }

  function formula(symbolic, substitution, meaning) {
    const box = document.createElement('div');
    box.className = 'formula';
    const a = document.createElement('div');
    a.className = 'symbolic';
    a.textContent = symbolic;
    const b = document.createElement('div');
    b.className = 'substitution';
    b.textContent = substitution;
    const c = document.createElement('div');
    c.className = 'meaning';
    c.textContent = meaning;
    box.append(a, b, c);
    return box;
  }

  function renderFormulas(snapshot) {
    const list = $('formula-list');
    list.replaceChildren();
    const posInput = int(snapshot.positive_input_tokens);
    const content = Math.max(posInput - 2, 0);
    const maxChunks = int(snapshot.max_chunks, 8);
    const k = Math.max(arr(snapshot.positive_chunk_tokens).length, arr(snapshot.negative_chunk_tokens).length, 1);
    const hidden = int(snapshot.hidden_dim);
    const cfg = num(snapshot.cfg, 1);
    const step = int(snapshot.diffusion_step);
    const total = int(snapshot.diffusion_total);
    const t = num(snapshot.timestep);

    list.append(
      formula('K = min(Kmax, ceil(Ncontent / 75))', `Ncontent=${content}, Kmax=${maxChunks} ⇒ 实际 K=${k}`, '长提示词被切成多个固定 77-slot CLIP 图；模型权重和 QNN 输入 shape 不变。'),
      formula('Cₖ = CLIP(Tₖ),   Cₖ ∈ R^(77×hidden)', `77 × ${hidden || 'hidden'} · K=${k}`, '每个 chunk 独立编码成条件向量。'),
      formula('εₜ⁽ᵏ⁾ = εᵤ,ₜ⁽ᵏ⁾ + s(εc,ₜ⁽ᵏ⁾ − εᵤ,ₜ⁽ᵏ⁾)', `s=CFG=${cfg} · skip-uncond=${Boolean(snapshot.skip_uncond)}`, 'CFG=1 且运行时允许时可跳过 unconditional 分支。'),
      formula('ε̄ₜ = (1/K) Σₖ εₜ⁽ᵏ⁾', `K=${k} · 当前 step ${step}/${total || '—'}`, 'H4 延续 H2 的真实多 chunk UNet 执行后取均值融合。'),
      formula('zₜ₋₁ = Scheduler(zₜ, ε̄ₜ, t)', `t=${Number.isFinite(t) ? t.toFixed(2) : '—'} · Scheduler seen=${Boolean(snapshot.scheduler_seen)}`, 'Scheduler 用当前噪声预测更新 latent；即使测得 0 ms，也视为真实观察到。'),
    );
  }

  function timelineEventLabel(e) {
    if (e.phase === 'unet_step') return `UNet ${int(e.diffusion_step)}/${int(e.diffusion_total)}`;
    if (e.phase === 'scheduler_step') return `Sched ${int(e.diffusion_step)}/${int(e.diffusion_total)}`;
    if (e.phase === 'vae_decode') return 'VAE decode';
    if (e.phase === 'clip') return 'CLIP';
    if (e.phase === 'prompt') return 'Prompt';
    if (e.phase === 'complete') return 'Complete';
    return text(e.phase);
  }

  function renderTimeline(snapshot) {
    const timeline = $('timeline');
    timeline.replaceChildren();
    const events = arr(snapshot.events).filter((e) => ['prompt','clip','unet_step','scheduler_step','vae_decode','complete'].includes(e.phase));
    const totalMs = Math.max(int(snapshot.total_ms), ...events.map((e) => int(e.elapsed_ms)), 1);
    let previousElapsed = -1;
    let anomalies = 0;

    events.forEach((e) => {
      const elapsed = Math.max(int(e.elapsed_ms), 0);
      const duration = Math.max(int(e.duration_ms), 0);
      const start = Math.max(elapsed - duration, 0);
      const row = document.createElement('div');
      row.className = `timeline-row ${text(e.phase, 'event')}`;
      if (previousElapsed >= 0 && elapsed < previousElapsed) {
        row.classList.add('nonmonotonic');
        anomalies += 1;
      }
      previousElapsed = Math.max(previousElapsed, elapsed);

      const label = document.createElement('div');
      label.className = 'timeline-label';
      label.textContent = timelineEventLabel(e);
      const track = document.createElement('div');
      track.className = 'timeline-track';
      const bar = document.createElement('div');
      bar.className = 'timeline-bar';
      const left = clamp(start / totalMs * 100, 0, 100);
      const width = Math.max(duration / totalMs * 100, 0.25);
      bar.style.left = `${left}%`;
      bar.style.width = `${Math.min(width, 100 - left)}%`;
      bar.title = `+${elapsed}ms · dur=${duration}ms`;
      track.appendChild(bar);
      const d = document.createElement('div');
      d.className = 'timeline-duration';
      d.textContent = `${duration}ms`;
      row.append(label, track, d);
      timeline.appendChild(row);
    });

    if (!events.length) {
      const empty = document.createElement('div');
      empty.className = 'warning';
      empty.textContent = '等待 native trace；H4 不用假时间轴填充空白。';
      timeline.appendChild(empty);
    }

    $('timeline-total').textContent = anomalies > 0
      ? `总计 ${totalMs} ms · 检测到 ${anomalies} 个非单调时间戳`
      : `总计 ${totalMs} ms · native monotonic trace`;
  }

  function renderTensor(snapshot) {
    const grid = $('tensor-grid');
    grid.replaceChildren();
    const values = [
      ['CLIP seq', int(snapshot.seq_len) || '—'],
      ['Hidden', int(snapshot.hidden_dim) || '—'],
      ['Latent', int(snapshot.latent_width) > 0 ? `${int(snapshot.latent_width)} × ${int(snapshot.latent_height)}` : '—'],
      ['Chunks', Math.max(arr(snapshot.positive_chunk_tokens).length, arr(snapshot.negative_chunk_tokens).length, int(snapshot.chunk_count, 1))],
      ['UNet observed', snapshot.unet_seen ? 'YES' : 'NO'],
      ['Scheduler observed', snapshot.scheduler_seen ? 'YES' : 'NO'],
    ];
    values.forEach(([label, value]) => {
      const item = document.createElement('div');
      item.className = 'tensor-item';
      const span = document.createElement('span');
      span.textContent = label;
      const strong = document.createElement('strong');
      strong.textContent = String(value);
      item.append(span, strong);
      grid.appendChild(item);
    });
  }

  function renderEvidence(snapshot) {
    $('positive-token-ids').textContent = arr(snapshot.positive_token_ids).join(' ') || '—';
    $('negative-token-ids').textContent = arr(snapshot.negative_token_ids).join(' ') || '—';
    $('raw-events').textContent = arr(snapshot.events).map((e) => JSON.stringify(e)).join('\n') || '等待真实 trace…';
  }

  function renderHero(snapshot) {
    const phase = text(snapshot.phase, 'idle');
    $('phase-value').textContent = phase.toUpperCase();
    const progress = phase === 'complete' ? 1 : clamp(num(snapshot.trace_progress), 0, 1);
    $('progress-value').textContent = `${Math.round(progress * 100)}%`;
    $('backend-value').textContent = text(snapshot.backend, 'NPU/QNN');
    const w = int(snapshot.width);
    const h = int(snapshot.height);
    $('resolution-value').textContent = w > 0 && h > 0 ? `${w}×${h}` : '—';
    $('stage-explain').textContent = phaseCopy[phase] || `真实阶段：${phase}`;
  }

  function update(snapshot) {
    const s = snapshot && typeof snapshot === 'object' ? snapshot : {};
    renderHero(s);
    renderPipeline(s);
    renderTokenChunks(s);
    renderFormulas(s);
    renderTimeline(s);
    renderTensor(s);
    renderEvidence(s);
  }

  window.S24UMicroscope = { update };
  update({ phase: 'idle', trace_progress: 0, backend: 'NPU/QNN', max_chunks: 8, events: [] });
})();
