import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import type { GenerationJob, GenerationRequest } from "../../domain/generation";
import type { ModelRecord } from "../../domain/models";
import { useDreamProvider } from "../providers";
import { generationStatusLabel, isGenerationTerminal } from "../generate-state";

const defaultRequest: GenerationRequest = {
  prompt: "a serene mountain lake at sunrise, cinematic lighting, ultra detailed",
  negativePrompt: "low quality, blurry, text, watermark",
  modelId: "cyberrealistic-v10-dmd2",
  width: 832,
  height: 1216,
  steps: 8,
  cfg: 1.2,
  seed: 20260906,
  fusionMode: "none",
  traceLevel: "basic",
};

export function GeneratePage() {
  const provider = useDreamProvider();
  const [models, setModels] = useState<ModelRecord[]>([]);
  const [request, setRequest] = useState<GenerationRequest>(defaultRequest);
  const [job, setJob] = useState<GenerationJob | null>(null);
  const [loadingModels, setLoadingModels] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setLoadingModels(true);
    void provider.listModels().then((items) => {
      if (!active) return;
      setModels(items);
      setRequest((current) => ({ ...current, modelId: items.some((item) => item.id === current.modelId) ? current.modelId : items[0]?.id ?? "" }));
    }).catch((reason: unknown) => {
      if (active) setError(reason instanceof Error ? reason.message : "Unable to load models");
    }).finally(() => { if (active) setLoadingModels(false); });
    return () => { active = false; };
  }, [provider]);

  useEffect(() => {
    if (!job || isGenerationTerminal(job.state)) return;
    let active = true;
    const poll = async () => {
      try {
        const next = await provider.getJob(job.id);
        if (active) setJob(next);
      } catch (reason: unknown) {
        if (active) setError(reason instanceof Error ? reason.message : "Unable to read generation job");
      }
    };
    void poll();
    const timer = window.setInterval(() => void poll(), 100);
    return () => { active = false; window.clearInterval(timer); };
  }, [job, provider]);

  const update = <K extends keyof GenerationRequest>(key: K, value: GenerationRequest[K]) => setRequest((current) => ({ ...current, [key]: value }));

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!request.prompt.trim() || !request.modelId || job && !isGenerationTerminal(job.state)) return;
    setError(null);
    try {
      const handle = await provider.generate({ ...request, prompt: request.prompt.trim() });
      setJob({ id: handle.id, request, state: "queued", progress: 0, message: "Submitting to the local queue" });
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "Generation failed");
    }
  };

  const running = Boolean(job && !isGenerationTerminal(job.state));
  const selectedModel = models.find((item) => item.id === request.modelId);

  return (
    <section className="generate-layout">
      <form className="surface-card generate-form" onSubmit={submit}>
        <div className="card-head"><span>GENERATION REQUEST</span><span className="truth-label truth-demo">MOCK PROVIDER</span></div>
        <label className="field-label" htmlFor="prompt">Prompt</label>
        <textarea id="prompt" value={request.prompt} onChange={(event) => update("prompt", event.target.value)} rows={4} placeholder="Describe the image you want to create" />
        <label className="field-label" htmlFor="negative-prompt">Negative prompt</label>
        <textarea id="negative-prompt" value={request.negativePrompt} onChange={(event) => update("negativePrompt", event.target.value)} rows={2} />
        <div className="form-grid">
          <label className="field-label">Model<select aria-label="Model" value={request.modelId} disabled={loadingModels || models.length === 0} onChange={(event) => update("modelId", event.target.value)}>{loadingModels ? <option>Loading models…</option> : models.map((model) => <option value={model.id} key={model.id}>{model.displayName}</option>)}</select></label>
          <label className="field-label">Seed<input aria-label="Seed" type="number" value={request.seed === "random" ? "" : request.seed} onChange={(event) => update("seed", Number(event.target.value))} /></label>
          <label className="field-label">Width<input aria-label="Width" type="number" min="256" step="8" value={request.width} onChange={(event) => update("width", Number(event.target.value))} /></label>
          <label className="field-label">Height<input aria-label="Height" type="number" min="256" step="8" value={request.height} onChange={(event) => update("height", Number(event.target.value))} /></label>
          <label className="field-label">Steps<input aria-label="Steps" type="number" min="1" max="50" value={request.steps} onChange={(event) => update("steps", Number(event.target.value))} /></label>
          <label className="field-label">CFG<input aria-label="CFG" type="number" min="0" step="0.1" value={request.cfg} onChange={(event) => update("cfg", Number(event.target.value))} /></label>
        </div>
        <div className="form-footer"><div className="request-meta"><span>{selectedModel?.architecture ?? "—"}</span><span>{selectedModel?.format ?? "—"}</span><span className="text-success">{selectedModel?.verified ? "Verified" : "Unavailable"}</span></div><button className="primary-button" type="submit" disabled={loadingModels || !request.prompt.trim() || !request.modelId || running}>{running ? "Generating…" : "Generate image"}</button></div>
        {error && <div role="alert" className="error-panel">{error}</div>}
      </form>
      <GenerationInspector job={job} />
    </section>
  );
}

function GenerationInspector({ job }: { job: GenerationJob | null }) {
  if (!job) {
    return <aside className="surface-card generation-inspector"><div className="card-kicker">JOB INSPECTOR</div><div className="empty-state"><span className="empty-icon">◌</span><span>Generation status will appear here.</span></div><div className="inspector-note"><span className="truth-label truth-unavailable">UNAVAILABLE</span><span>Backend execution is not connected in GUI Alpha.</span></div></aside>;
  }
  return <aside className="surface-card generation-inspector"><div className="card-head"><span>JOB INSPECTOR</span><span className={`truth-label ${job.state === "complete" ? "truth-observed" : job.state === "failed" ? "truth-unavailable" : "truth-derived"}`}>{generationStatusLabel(job.state)}</span></div><div className="job-state"><strong>{generationStatusLabel(job.state)}</strong><span>{job.message}</span></div><div className="progress-track" role="progressbar" aria-label="Generation progress" aria-valuemin={0} aria-valuemax={100} aria-valuenow={job.progress}><span style={{ width: `${job.progress}%` }} /></div><div className="progress-reading"><span>Progress</span><strong>{job.progress}%</strong></div>{job.result ? <div className="result-wrap"><img src={job.result.imageUrl} alt="Mock generated result" /><div className="result-caption"><span>Result ready</span><span className="truth-label truth-demo">DEMO DATA</span></div></div> : <div className="inspector-note"><span className="truth-label truth-derived">LOCAL QUEUE</span><span>Polling the typed provider contract.</span></div>}</aside>;
}
