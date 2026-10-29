import { useEffect, useRef, useState } from "react";
import { activeImageJob, imageModeLabels, researchImageApi, validImageJobId, type ImageJob, type ImageSettings } from "../../../providers/research-image-api";
import "./research-experiments.css";

const savedJobKey = "dream.fusionImageJob";
const stateLabels = { queued: "排队中", running: "生成中", cancelling: "正在取消", cancelled: "已取消", complete: "已完成", failed: "失败" };
const defaults: Omit<ImageSettings, "requestId"> = { modelId: "realistic-vision-v5.1-fusion", prompt: "a serene mountain lake at sunrise, photorealistic, soft natural light", negativePrompt: "blurry, low quality, text, watermark", seed: 42, steps: 12, cfg: 5.5, alpha: .5, width: 512, height: 512 };
const errorText = (reason: unknown) => reason instanceof Error ? reason.message : "图像实验请求失败";
const remember = (id: string) => { try { localStorage.setItem(savedJobKey, id); } catch { /* Result remains available in this view. */ } };

export function ResearchImageExperiment() {
  const [open, setOpen] = useState(false), [ready, setReady] = useState(false), [busy, setBusy] = useState(false);
  const [settings, setSettings] = useState(defaults), [job, setJob] = useState<ImageJob | null>(null), [error, setError] = useState("");
  const [imageErrors, setImageErrors] = useState<string[]>([]);
  const lastRequest = useRef<{ key: string; payload: ImageSettings } | null>(null);
  const sending = useRef(false), activeController = useRef<AbortController | null>(null);
  const active = activeImageJob(job);
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController(); setReady(false); setBusy(true); setError("");
    void (async () => {
      try {
        await researchImageApi.capability(controller.signal);
        if (controller.signal.aborted) return;
        setReady(true);
        if (lastRequest.current) {
          // An unknown submission takes precedence over the last acknowledged job.
          const { requestId: _requestId, ...snapshot } = lastRequest.current.payload;
          setSettings(snapshot);
          return;
        }
        let stored: string | null = null;
        try { stored = localStorage.getItem(savedJobKey); } catch { /* Storage can be disabled. */ }
        if (stored && validImageJobId(stored)) {
          const value = await researchImageApi.get(stored, controller.signal);
          if (!controller.signal.aborted) {
            setJob(value); setImageErrors([]);
            const { requestId: _requestId, ...snapshot } = value.settings;
            setSettings(snapshot);
          }
        }
      } catch (reason) { if (!controller.signal.aborted) setError(errorText(reason)); }
      finally { if (!controller.signal.aborted) setBusy(false); }
    })();
    return () => { controller.abort(); activeController.current?.abort(); sending.current = false; };
  }, [open]);

  useEffect(() => {
    if (!open || !job || !active) return;
    const controller = new AbortController(); let timer: number | undefined;
    const id = job.id;
    const poll = async () => {
      try {
        const value = await researchImageApi.get(id, controller.signal);
        if (controller.signal.aborted) return;
        setJob(value); setError("");
        if (!activeImageJob(value)) return;
      } catch (reason) { if (!controller.signal.aborted) setError(errorText(reason)); }
      if (!controller.signal.aborted) timer = window.setTimeout(() => void poll(), 1000);
    };
    timer = window.setTimeout(() => void poll(), 1000);
    return () => { controller.abort(); window.clearTimeout(timer); };
  }, [open, job?.id, active]);

  const submit = async () => {
    if (!ready || sending.current || active || busy) return;
    sending.current = true; setBusy(true); setError(""); setImageErrors([]);
    const controller = new AbortController(); activeController.current = controller;
    const key = JSON.stringify(settings);
    if (lastRequest.current?.key !== key) lastRequest.current = { key, payload: { ...settings, requestId: crypto.randomUUID() } };
    try {
      const value = await researchImageApi.submit(lastRequest.current.payload, controller.signal);
      if (!controller.signal.aborted) { setJob(value); remember(value.id); lastRequest.current = null; }
    } catch (reason) { if (!controller.signal.aborted) setError(errorText(reason)); }
    finally { if (!controller.signal.aborted) { sending.current = false; setBusy(false); } }
  };
  const cancel = async () => {
    if (!job || sending.current) return;
    sending.current = true; setBusy(true); setError("");
    const controller = new AbortController(); activeController.current = controller;
    try {
      const value = await researchImageApi.cancel(job.id, controller.signal);
      if (!controller.signal.aborted) setJob(value);
    } catch (reason) { if (!controller.signal.aborted) setError(errorText(reason)); }
    finally { if (!controller.signal.aborted) { sending.current = false; setBusy(false); } }
  };
  const result = job?.state === "complete" ? job.result : null;
  return <section className="surface-card research-experiment-panel" aria-label="受控融合图像生成">
    <button className="secondary-button" type="button" aria-expanded={open} onClick={() => setOpen(v => !v)}>受控融合图像实验</button>
    {open && <>
      <h2>四种融合 · 同一初始噪声</h2>
      <p>Realistic Vision SD1.5 · 受控 Diffusers 引擎，不代表手机或 native 等价；不启用 FaceID。逐步执行成对正负 chunk CFG，融合预测后推进一次调度器。</p>
      <p>使用已有本地模型，四张图按顺序生成。每侧最多 300 个内容 token（4 块），超限拒绝；只有一块时四种模式结果应一致。</p>
      <p>提示词按 CLIP 原始 token 分块，括号和权重语法视为普通文本。</p>
      <form onSubmit={event => { event.preventDefault(); void submit(); }}>
        <fieldset disabled={busy || active} className="research-image-fields">
          <label>实验正向提示词<textarea required maxLength={2000} value={settings.prompt} onChange={e => setSettings({ ...settings, prompt: e.target.value })} /></label>
          <label>实验负向提示词<textarea maxLength={2000} value={settings.negativePrompt} onChange={e => setSettings({ ...settings, negativePrompt: e.target.value })} /></label>
          <div className="research-image-parameters">
            {([['seed', '实验种子', 0, 2147483647, 1], ['steps', '每张步数', 1, 30, 1], ['cfg', '实验 CFG', 1, 15, .1], ['alpha', '残差 α', 0, 1, .05]] as const).map(([key, label, min, max, step]) =>
              <label key={key}>{label}<input type="number" required min={min} max={max} step={step} value={settings[key]} onChange={e => setSettings({ ...settings, [key]: Number(e.target.value) })} /></label>)}
            {([['width', '实验宽度'], ['height', '实验高度']] as const).map(([key, label]) => <label key={key}>{label}<select value={settings[key]} onChange={e => setSettings({ ...settings, [key]: Number(e.target.value) })}>{[256, 320, 384, 448, 512].map(v => <option key={v} value={v}>{v}</option>)}</select></label>)}
          </div>
        </fieldset>
        <button className="primary-button" type="submit" disabled={!ready || busy || active}>生成四种融合图像</button>
        {active && <button className="secondary-button" type="button" disabled={busy || job?.state === "cancelling"} onClick={() => void cancel()}>取消图像实验</button>}
      </form>
      {error && <p role="alert" className="inline-error">{error}</p>}
      {job && <div role="status"><strong>{stateLabels[job.state]}</strong><p>{job.message} · {job.progress}%</p><code className="research-digest">{job.id}</code>{job.error && <p className="inline-error">{job.error}</p>}</div>}
      {result && <>
        <p>结果参数：种子 {job!.settings.seed} · {job!.settings.steps} 步 · CFG {job!.settings.cfg} · α {job!.settings.alpha} · {job!.settings.width} × {job!.settings.height}</p>
        <div className="research-image-grid">{result.variants.map(variant => <figure key={variant.mode}>
          {imageErrors.includes(variant.mode) ? <><p role="alert">图片加载失败，可重试读取已保存的图片。</p>
            <button className="secondary-button" type="button" onClick={() => setImageErrors(values => values.filter(mode => mode !== variant.mode))}>重试{imageModeLabels[variant.mode]}图片</button></>
            : <img key={variant.imageUrl} src={variant.imageUrl} alt={`${imageModeLabels[variant.mode]}生成结果`} width={job!.settings.width} height={job!.settings.height} onError={() => setImageErrors(values => [...values, variant.mode])} />}
          <figcaption><strong>{imageModeLabels[variant.mode]}</strong><p>权重 {variant.effectiveWeights.map(v => v.toFixed(4)).join(" / ")} · {(variant.durationMs / 1000).toFixed(1)} 秒</p><a href={variant.imageUrl} download={`${job!.id}-${variant.mode}.png`}>保存图片</a></figcaption>
        </figure>)}</div>
        <details><summary>实验来源与实际编码记录</summary>
          <p>{result.provenance.scheduler} · {result.provenance.predictionType} · torch {result.provenance.torchVersion} · diffusers {result.provenance.diffusersVersion}</p>
          <p>实际内容 token（正 / 负）：{result.provenance.chunkCounts.map(c => `${c.positive} / ${c.negative}`).join("；")} · 负向编码{result.provenance.negativeEncodingPerformed ? "已执行" : "因 CFG=1 跳过"}</p>
          <p>模型 SHA-256</p><code className="research-digest">{result.provenance.modelSha256}</code>
          <p>共同初始噪声 SHA-256</p><code className="research-digest">{result.provenance.initialLatentSha256}</code>
          <p>引擎代码 SHA-256</p><code className="research-digest">{result.provenance.engineRevision}</code>
          <pre className="research-encoded-tokens">{JSON.stringify(result.provenance.encodedTokenIds, null, 2)}</pre>
        </details>
      </>}
    </>}
  </section>;
}
