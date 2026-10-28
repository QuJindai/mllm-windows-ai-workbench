import { useEffect, useReducer, useRef, useState } from "react";
import type { FormEvent } from "react";
import type { GenerationBatchItem, GenerationJob, GenerationPreset, GenerationRequest } from "../../domain/generation";
import type { HardwareSnapshot } from "../../domain/hardware";
import { isFreshHardware } from "../../domain/hardware";
import type { ModelRecord } from "../../domain/models";
import { useDreamProvider } from "../providers";
import { DeleteImageButton } from "../components/DeleteImageButton";
import { ScenePresetPicker } from "../components/ScenePresetPicker";
import { useDeletedImageIds } from "../image-deletion";
import { generationStatusLabel, isGenerationTerminal } from "../generate-state";
import { generationQualityWarning, MIN_GENERATION_DIMENSION, MIN_GENERATION_STEPS } from "../../domain/generation-quality";

const defaultRequest: GenerationRequest = {
  prompt: "a serene mountain lake at sunrise, cinematic lighting, ultra detailed",
  negativePrompt: "low quality, blurry, text, watermark",
  modelId: "cyberrealistic-xl-v10-standard",
  width: 768,
  height: 768,
  steps: 20,
  cfg: 4.0,
  samplingMethod: "dpm++2m_sde",
  scheduler: "karras",
  seed: 20260906,
  fusionMode: "none",
  traceLevel: "basic",
};

const ILLUSTRIOUS_MODEL_ID = "illustrious-xl-v2.0";
const animeBaselinePrompt = "masterpiece, best quality, very aesthetic, anime screencap, clean lineart, cel shading, 1girl, solo, adult woman, portrait, long brown hair, brown eyes, white jacket, brown shirt, necklace, looking at viewer, closed mouth, simple light background";
const animeBaselineNegative = "worst quality, low quality, lowres, blurry, sketch, watercolor, oil painting, rough brush strokes, unfinished, photorealistic, 3d, child, text, watermark, signature, multiple views, multiple people, bad anatomy";

type GenerateTab = "prompt" | "presets" | "advanced";
type PreviewTab = "preview" | "metadata" | "variants";
type QueueEntry = GenerationBatchItem & { handleId?: string };
type QueueRun = {
  id: number;
  stopRequested: boolean;
  stopSignal: Promise<void>;
  requestStop: () => void;
  handleId: string | null;
  entryId: string | null;
  cancellation: Promise<GenerationJob> | null;
};
type QueueState = {
  runId: number | null;
  status: "idle" | "running" | "stopping" | "stopped" | "complete";
  entries: QueueEntry[];
  results: GenerationBatchItem[];
};
type QueueAction =
  | { type: "queue-started"; runId: number; entries: QueueEntry[] }
  | { type: "handle-received"; runId: number; entryId: string; handleId: string }
  | { type: "job-updated"; runId: number; entryId: string; job: GenerationJob }
  | { type: "entry-cancelled"; runId: number; entryId: string }
  | { type: "entry-failed"; runId: number; entryId: string; error: string }
  | { type: "queue-stopping"; runId: number }
  | { type: "queue-stopped"; runId: number }
  | { type: "queue-finished"; runId: number };

const initialQueueState: QueueState = { runId: null, status: "idle", entries: [], results: [] };

function stopUnsubmittedEntries(entries: QueueEntry[]): QueueEntry[] {
  return entries.map((entry) => !entry.handleId && !isGenerationTerminal(entry.state)
    ? { ...entry, state: "cancelled", progress: 0, message: "队列已停止" }
    : entry);
}

function queueReducer(state: QueueState, action: QueueAction): QueueState {
  if (action.type !== "queue-started" && action.runId !== state.runId) return state;
  switch (action.type) {
    case "queue-started":
      return { runId: action.runId, status: "running", entries: action.entries, results: [] };
    case "handle-received":
      return {
        ...state,
        entries: state.entries.map((entry) => entry.id === action.entryId
          ? { ...entry, handleId: action.handleId, state: "queued", message: "已提交到本地队列" }
          : entry),
      };
    case "job-updated": {
      let completed: QueueEntry | undefined;
      const entries = state.entries.map((entry) => {
        if (entry.id !== action.entryId) return entry;
        completed = {
          ...entry,
          state: action.job.state,
          progress: action.job.progress,
          message: action.job.message,
          result: action.job.result,
          error: action.job.error,
        };
        return completed;
      });
      const results = action.job.result && completed
        ? [...state.results.filter((item) => item.id !== completed?.id), completed]
        : state.results;
      return { ...state, entries, results };
    }
    case "entry-cancelled":
      return {
        ...state,
        entries: state.entries.map((entry) => entry.id === action.entryId
          ? { ...entry, state: "cancelled", progress: 0, message: "已取消生成" }
          : entry),
      };
    case "entry-failed":
      return {
        ...state,
        entries: state.entries.map((entry) => entry.id === action.entryId
          ? { ...entry, state: "failed", progress: 0, message: "生成失败", error: action.error }
          : entry),
      };
    case "queue-stopping":
      return { ...state, status: "stopping", entries: stopUnsubmittedEntries(state.entries) };
    case "queue-stopped":
      return { ...state, status: "stopped", entries: stopUnsubmittedEntries(state.entries) };
    case "queue-finished":
      return state.status === "running" ? { ...state, status: "complete" } : state;
  }
}

const PRESETS_KEY = "dream-windows-generation-presets";
const JOB_POLL_INTERVAL_MS = 750;
const wait = (milliseconds: number) => new Promise<void>((resolve) => window.setTimeout(resolve, milliseconds));

function formatMetadataValue(value: unknown): string {
  if (value === undefined) return "—";
  if (value === null) return "null";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean" || typeof value === "bigint") return String(value);
  try {
    return JSON.stringify(value) ?? String(value);
  } catch {
    return "[无法序列化]";
  }
}

export function GeneratePage({ hardware, hardwareError, initialRequest }: { hardware?: HardwareSnapshot | null; hardwareError?: string | null; initialRequest?: Partial<GenerationRequest> }) {
  const provider = useDreamProvider();
  const [models, setModels] = useState<ModelRecord[]>([]);
  const [request, setRequest] = useState<GenerationRequest>({ ...defaultRequest, ...initialRequest });
  const [job, setJob] = useState<GenerationJob | null>(null);
  const deletedImages = useDeletedImageIds();
  const visibleJob = job?.result && deletedImages.has(job.result.id) ? { ...job, result: undefined, message: "图片已删除，生成参数仍保留" } : job;
  const [queueState, dispatchQueue] = useReducer(queueReducer, initialQueueState);
  const [tab, setTab] = useState<GenerateTab>("prompt");
  const [batchCount, setBatchCount] = useState(1);
  const [presets, setPresets] = useState<GenerationPreset[]>([]);
  const [presetName, setPresetName] = useState("");
  const [loadingModels, setLoadingModels] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const nextRunId = useRef(0);
  const activeRun = useRef<QueueRun | null>(null);
  // Monitoring is advisory; only generation preflight can establish inference readiness.
  const telemetryUnknown = Boolean(hardwareError) || (!hardware && (hardware !== undefined || provider.mode === "backend"))
    || Boolean(hardware && provider.mode === "backend" && (hardware.truth !== "observed" || !isFreshHardware(hardware)));
  const telemetryWarning = telemetryUnknown
    ? `${hardwareError ?? "尚无有效硬件采样"}。当前硬件状态未知；可提交生成，由后端执行安全预检。`
    : hardware?.cudaReady === false ? "硬件采样报告 CUDA 不可用；可提交生成，由后端执行安全预检。" : null;
  const staleSample = telemetryUnknown && hardware?.truth === "observed" && Number.isFinite(Date.parse(hardware.sampledAt ?? "")) ? hardware : null;
  const selectedModel = models.find((item) => item.id === request.modelId);
  const recommendedSteps = selectedModel?.generationDefaults?.steps;
  const qualityWarning = generationQualityWarning(
    request,
    recommendedSteps !== undefined && recommendedSteps < MIN_GENERATION_STEPS
      ? {
          minimumSteps: recommendedSteps,
          recommendedSteps,
          profileLabel: "当前模型按低步数蒸馏配置采样",
        }
      : undefined,
  );
  const queue = queueState.entries;
  const results = queueState.results.filter(item => item.result && !deletedImages.has(item.result.id));

  useEffect(() => {
    if (initialRequest) setRequest((current) => ({ ...current, ...initialRequest }));
  }, [initialRequest]);

  useEffect(() => {
    let active = true;
    setLoadingModels(true);
    void provider.listModels().then((items) => {
      if (!active) return;
      setModels(items);
      setRequest((current) => ({ ...current, modelId: items.some((item) => item.id === current.modelId) ? current.modelId : items[0]?.id ?? "" }));
    }).catch((reason: unknown) => {
      if (active) setError(reason instanceof Error ? reason.message : "无法加载模型");
    }).finally(() => { if (active) setLoadingModels(false); });
    return () => { active = false; };
  }, [provider]);

  useEffect(() => {
    try {
      const saved = JSON.parse(window.localStorage.getItem(PRESETS_KEY) ?? "[]") as GenerationPreset[];
      if (Array.isArray(saved)) setPresets(saved.filter((preset) => preset?.id && preset?.name && preset?.request));
    } catch {
      setPresets([]);
    }
  }, []);

  const update = <K extends keyof GenerationRequest>(key: K, value: GenerationRequest[K]) => setRequest((current) => ({ ...current, [key]: value }));

  const selectModel = (modelId: string) => {
    const generationDefaults = models.find((model) => model.id === modelId)?.generationDefaults;
    setRequest((current) => ({ ...current, modelId, ...(generationDefaults ?? {}) }));
  };

  const isActiveRun = (run: QueueRun) => activeRun.current === run;

  const cancelRunHandle = async (run: QueueRun): Promise<GenerationJob | null> => {
    if (!run.handleId || !run.entryId) return null;
    try {
      if (!run.cancellation) run.cancellation = provider.cancelJob(run.handleId);
      const cancelled = await run.cancellation;
      if (!isActiveRun(run)) return cancelled;
      setJob(cancelled);
      dispatchQueue({ type: "job-updated", runId: run.id, entryId: run.entryId, job: cancelled });
      return cancelled;
    } catch (reason: unknown) {
      if (isActiveRun(run)) setError(reason instanceof Error ? reason.message : "无法取消生成");
      return null;
    }
  };

  useEffect(() => () => {
    const run = activeRun.current;
    if (!run) return;
    run.stopRequested = true;
    run.requestStop();
    activeRun.current = null;
    if (run.handleId && !run.cancellation) {
      run.cancellation = provider.cancelJob(run.handleId);
      void run.cancellation.catch(() => undefined);
    }
  }, [provider]);

  const runQueue = async (entries: QueueEntry[], run: QueueRun) => {
    for (const entry of entries) {
      if (run.stopRequested || !isActiveRun(run)) break;
      try {
        const handle = await provider.generate(entry.request);
        run.handleId = handle.id;
        run.entryId = entry.id;
        if (run.stopRequested || !isActiveRun(run)) {
          await cancelRunHandle(run);
          break;
        }
        dispatchQueue({ type: "handle-received", runId: run.id, entryId: entry.id, handleId: handle.id });
        let current: GenerationJob = { id: handle.id, request: entry.request, state: "queued", progress: 0, message: "已提交到本地队列" };
        while (!isGenerationTerminal(current.state)) {
          if (run.stopRequested || !isActiveRun(run)) break;
          await wait(JOB_POLL_INTERVAL_MS);
          if (run.stopRequested || !isActiveRun(run)) break;
          const poll = await Promise.race([
            provider.getJob(handle.id).then(
              (job) => ({ type: "job", job } as const),
              (reason: unknown) => ({ type: "error", reason } as const),
            ),
            run.stopSignal.then(() => ({ type: "stopped" } as const)),
          ]);
          if (poll.type === "stopped" || run.stopRequested || !isActiveRun(run)) break;
          if (poll.type === "error") throw poll.reason;
          if (run.stopRequested || !isActiveRun(run)) break;
          current = poll.job;
          setJob(current);
          dispatchQueue({ type: "job-updated", runId: run.id, entryId: entry.id, job: current });
        }
        if (run.stopRequested && !isGenerationTerminal(current.state)) {
          await cancelRunHandle(run);
          if (isActiveRun(run)) dispatchQueue({ type: "entry-cancelled", runId: run.id, entryId: entry.id });
          break;
        }
        if (isActiveRun(run)) setJob(current);
      } catch (reason: unknown) {
        if (!isActiveRun(run)) break;
        const message = reason instanceof Error ? reason.message : "生成失败";
        run.stopRequested = true;
        dispatchQueue({ type: "entry-failed", runId: run.id, entryId: entry.id, error: message });
        dispatchQueue({ type: "queue-stopped", runId: run.id });
        setError(message);
        break;
      } finally {
        if (run.entryId === entry.id) {
          run.handleId = null;
          run.entryId = null;
          run.cancellation = null;
        }
      }
    }
    if (isActiveRun(run)) {
      dispatchQueue({ type: run.stopRequested ? "queue-stopped" : "queue-finished", runId: run.id });
      activeRun.current = null;
    }
  };

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (loadingModels || qualityWarning || !request.prompt.trim() || !request.modelId || activeRun.current || queueState.status === "running" || queueState.status === "stopping") return;
    setError(null);
    const entries: QueueEntry[] = Array.from({ length: Math.max(1, Math.min(8, batchCount)) }, (_, index) => {
      const seed = request.seed === "random" ? "random" : request.seed + index;
      return { id: `batch-${Date.now()}-${index}`, request: { ...request, prompt: request.prompt.trim(), seed }, state: "queued", progress: 0, message: "等待本地队列" };
    });
    let requestStop!: () => void;
    const stopSignal = new Promise<void>((resolve) => { requestStop = resolve; });
    const run: QueueRun = { id: ++nextRunId.current, stopRequested: false, stopSignal, requestStop, handleId: null, entryId: null, cancellation: null };
    activeRun.current = run;
    dispatchQueue({ type: "queue-started", runId: run.id, entries });
    void runQueue(entries, run);
  };

  const cancelActive = async () => {
    const run = activeRun.current;
    if (!run) return;
    run.stopRequested = true;
    run.requestStop();
    dispatchQueue({ type: "queue-stopping", runId: run.id });
    await cancelRunHandle(run);
  };

  const savePreset = () => {
    const name = presetName.trim();
    if (!name) return;
    const preset: GenerationPreset = { id: `preset-${Date.now()}`, name, request: { ...request } };
    const next = [...presets.filter((item) => item.name !== name), preset];
    setPresets(next);
    window.localStorage.setItem(PRESETS_KEY, JSON.stringify(next));
    setPresetName("");
  };

  const choosePreset = (preset: GenerationPreset) => {
    setRequest(preset.request);
    setTab("prompt");
  };
  const running = queueState.status === "running";
  const stopping = queueState.status === "stopping";
  const busy = running || stopping;

  return (
    <section className="generate-layout prototype-generate-layout">
      <div className="generate-main-column">
        <form className="surface-card generate-form" onSubmit={submit}>
          <div className="card-head"><span>生成请求</span><span className={`truth-label ${provider.mode === "mock" ? "truth-demo" : "truth-observed"}`}>{provider.mode === "mock" ? "模拟提供方" : "后端提供方"}</span></div>
          <div className="workbench-tabs" role="tablist" aria-label="生成设置">
            {(["prompt", "presets", "advanced"] as GenerateTab[]).map((value) => <button key={value} type="button" role="tab" aria-selected={tab === value} className={tab === value ? "is-active" : ""} onClick={() => setTab(value)}>{value === "prompt" ? "提示词" : value === "presets" ? "预设" : "高级"}</button>)}
          </div>
          {tab === "prompt" && <>
            <ScenePresetPicker modelId={request.modelId} prompt={request.prompt} negativePrompt={request.negativePrompt} disabled={busy || loadingModels}
              onApply={value => setRequest(current => ({ ...current, ...value }))} />
            <label className="field-label" htmlFor="prompt">正向提示词</label>
            <textarea id="prompt" value={request.prompt} onChange={(event) => update("prompt", event.target.value)} rows={4} placeholder="描述你想创建的图像" />
            <label className="field-label" htmlFor="negative-prompt">负向提示词</label>
            <textarea id="negative-prompt" value={request.negativePrompt} onChange={(event) => update("negativePrompt", event.target.value)} rows={2} />
            <div className="prompt-helper"><span>建议使用完整场景、主体数量和镜头描述。</span><span>{request.prompt.length}/2000</span></div>
          </>}
          {tab === "presets" && <PresetPanel presets={presets} presetName={presetName} onNameChange={setPresetName} onSave={savePreset} onChoose={choosePreset} />}
          {tab === "advanced" && <div className="advanced-notice"><strong>高级采样参数</strong><p>这些设置会原样传递到 native stable-diffusion.cpp；显微镜采集只增加可观测输出，不改变普通生成参数。</p></div>}
          {request.modelId === ILLUSTRIOUS_MODEL_ID && <div className="advanced-notice">
            <strong>Illustrious · 纯动漫画质基准</strong>
            <p>本页不加载 FaceID、人物 LoRA 或修脸。先验证线稿与色块，再到人物创作叠加身份条件；人物相似度不属于此基准。</p>
            <p>下方按钮会替换当前提示词、采样参数和种子，使用清晰赛璐璐头像示例。你的已保存预设与历史图片不变。</p>
            <button type="button" className="secondary-button" disabled={busy || !selectedModel?.generationDefaults}
              onClick={() => {
                setRequest(current => ({ ...current, ...selectedModel?.generationDefaults,
                  prompt: animeBaselinePrompt, negativePrompt: animeBaselineNegative,
                  seed: 202610101, fusionMode: "none", traceLevel: "basic" }));
                setTab("prompt");
              }}>应用清晰动漫基准</button>
          </div>}
          <div className="form-grid">
            <label className="field-label">模型<select aria-label="模型" value={request.modelId} disabled={loadingModels || models.length === 0} onChange={(event) => selectModel(event.target.value)}>{loadingModels ? <option>正在加载模型…</option> : models.map((model) => <option value={model.id} key={model.id}>{model.displayName}</option>)}</select></label>
            <label className="field-label">随机种子<input aria-label="随机种子" type="number" value={request.seed === "random" ? "" : request.seed} placeholder="留空为随机" onChange={(event) => update("seed", event.target.value === "" ? "random" : Number(event.target.value))} /></label>
            <label className="field-label">宽度<input aria-label="Width" type="number" min={MIN_GENERATION_DIMENSION} step="8" value={request.width} onChange={(event) => update("width", Number(event.target.value))} /></label>
            <label className="field-label">高度<input aria-label="Height" type="number" min={MIN_GENERATION_DIMENSION} step="8" value={request.height} onChange={(event) => update("height", Number(event.target.value))} /></label>
            <label className="field-label">步数<input aria-label="Steps" type="number" min={recommendedSteps !== undefined && recommendedSteps < MIN_GENERATION_STEPS ? recommendedSteps : MIN_GENERATION_STEPS} max="50" value={request.steps} onChange={(event) => update("steps", Number(event.target.value))} /></label>
            <label className="field-label">CFG<input aria-label="CFG" type="number" min="0" step="0.1" value={request.cfg} onChange={(event) => update("cfg", Number(event.target.value))} /></label>
            <label className="field-label">采样器<select aria-label="采样器" value={request.samplingMethod} onChange={(event) => update("samplingMethod", event.target.value as GenerationRequest["samplingMethod"])}><option value="dpm++2m_sde">DPM++ 2M SDE</option><option value="dpm++2m">DPM++ 2M</option><option value="lcm">LCM（仅蒸馏模型）</option><option value="euler">Euler</option><option value="euler_a">Euler Ancestral</option></select></label>
            <label className="field-label">调度器<select aria-label="调度器" value={request.scheduler} onChange={(event) => update("scheduler", event.target.value as GenerationRequest["scheduler"])}><option value="karras">Karras</option><option value="discrete">Discrete</option><option value="exponential">Exponential</option><option value="lcm">LCM</option></select></label>
            <label className="field-label">显微镜采集<select aria-label="显微镜采集" value={request.traceLevel} onChange={(event) => update("traceLevel", event.target.value as GenerationRequest["traceLevel"])}><option value="basic">仅阶段耗时</option><option value="h6">H6 条件影响与潜空间（研究采集）</option><option value="h7">H7 条件影响、潜空间与 Self/Cross 注意力</option></select></label>
            {(request.traceLevel === "h6" || request.traceLevel === "h7") && <p className="muted-copy">研究采集增加额外前向计算和文件写入，耗时、内存开销高于基础生成。H6 采集条件影响与潜空间；H7 还采集自注意力和交叉注意力。研究采集的宽、高各不超过 1024 像素，对应最多 128 × 128 潜空间网格。需要升级后的研究引擎；结果以实际产物为准。</p>}
            <label className="field-label">批量数量<input aria-label="批量数量" type="number" min="1" max="8" value={batchCount} onChange={(event) => setBatchCount(Math.max(1, Math.min(8, Number(event.target.value) || 1)))} /></label>
          </div>
          <div className="form-footer"><div className="request-meta"><span>{selectedModel?.architecture ?? "—"}</span><span>{selectedModel?.format ?? "—"}</span><span className={selectedModel?.verified ? "text-success" : "text-muted"}>{selectedModel?.verified ? "已验证" : "不可用"}</span><span>{batchCount > 1 ? `串行队列 ${batchCount} 张` : "单张生成"}</span></div><div className="generate-action-group"><button className="primary-button generate-submit" type="submit" disabled={loadingModels || Boolean(qualityWarning) || !request.prompt.trim() || !request.modelId || busy}>{stopping ? "正在停止…" : running ? "生成中…" : "生成图像"}</button>{running && <button className="danger-button" type="button" aria-label="取消生成" onClick={() => void cancelActive()}>取消生成</button>}</div></div>
          {qualityWarning && <div role="alert" className="quality-warning">{qualityWarning}</div>}
          {telemetryWarning && <div role="alert" aria-label="硬件监控提示" className="quality-warning">{telemetryWarning}{staleSample && <div>上次采样已过期（非当前状态）：<time dateTime={staleSample.sampledAt}>{new Date(staleSample.sampledAt!).toLocaleTimeString("zh-CN", { hour12: false })}</time> · GPU {staleSample.gpuUtil}% · 显存 {staleSample.vramUsedMiB} / {staleSample.vramTotalMiB} MiB</div>}</div>}
          {error && <div role="alert" className="error-panel">{error}</div>}
        </form>
        {queue.length > 0 && <BatchQueue entries={queue} stopped={stopping || queueState.status === "stopped"} />}
      </div>
      <GenerationPreview job={visibleJob} results={results} providerMode={provider.mode} onDelete={id => provider.deleteHistory(id)} />
      <GenerationInspector job={visibleJob} providerMode={provider.mode} queue={queue} />
    </section>
  );
}

function PresetPanel({ presets, presetName, onNameChange, onSave, onChoose }: { presets: GenerationPreset[]; presetName: string; onNameChange: (value: string) => void; onSave: () => void; onChoose: (preset: GenerationPreset) => void }) {
  return <div className="preset-panel"><div className="preset-save-row"><input aria-label="预设名称" placeholder="输入预设名称" value={presetName} onChange={(event) => onNameChange(event.target.value)} /><button className="secondary-button" type="button" disabled={!presetName.trim()} onClick={onSave}>保存预设</button></div>{presets.length === 0 ? <div className="empty-state preset-empty"><span className="empty-icon">☆</span><span>还没有保存的预设。</span></div> : <div className="preset-list">{presets.map((preset) => <button type="button" className="preset-item" aria-label={`选择预设 ${preset.name}`} key={preset.id} onClick={() => onChoose(preset)}><strong>{preset.name}</strong><span>{preset.request.width} × {preset.request.height} · {preset.request.steps} 步 · {preset.request.modelId}</span></button>)}</div>}</div>;
}

function BatchQueue({ entries, stopped }: { entries: QueueEntry[]; stopped: boolean }) {
  return <section className="surface-card batch-queue"><div className="section-title">批量队列 · {entries.length} 项 <span className={`truth-label ${stopped ? "truth-derived" : "truth-observed"}`}>{stopped ? "队列已停止" : "串行执行"}</span></div><div className="batch-entry-list">{entries.map((entry, index) => <div className="batch-entry" key={entry.id}><span className="batch-index">{index + 1}</span><div><strong>{generationStatusLabel(entry.state)}</strong><small>{entry.message}{entry.error ? ` · ${entry.error}` : ""}</small></div><span>{entry.progress}%</span></div>)}</div></section>;
}

function GenerationPreview({ job, results, providerMode, onDelete }: { job: GenerationJob | null; results: GenerationBatchItem[]; providerMode: "mock" | "backend"; onDelete: (id: string) => Promise<void> }) {
  const [tab, setTab] = useState<PreviewTab>("preview");
  const image = job?.result?.imageUrl;
  const labels: Record<PreviewTab, string> = { preview: "预览", metadata: "元数据", variants: `变体（${results.length}）` };
  const metadata = job ? [
    ["任务 ID", job.id],
    ["模型", job.request.modelId],
    ["尺寸", `${job.request.width} × ${job.request.height}`],
    ["步数", job.request.steps],
    ["CFG", job.request.cfg],
    ["随机种子", job.request.seed],
    ["采样器", job.request.samplingMethod],
    ["调度器", job.request.scheduler],
    ...Object.entries(job.result?.metadata ?? {}).filter(([key]) => !["width", "height", "modelId"].includes(key)),
  ] : [];
  return <section className="surface-card generation-preview">
    <div className="preview-tabs" role="tablist" aria-label="生成结果视图">
      {(["preview", "metadata", "variants"] as PreviewTab[]).map((value) => <button key={value} className={tab === value ? "is-active" : ""} type="button" role="tab" aria-selected={tab === value} onClick={() => setTab(value)}>{labels[value]}</button>)}
    </div>
    {tab === "preview" && <div className="generation-preview-panel" role="tabpanel" aria-label={labels.preview}>{image ? <><img src={image} alt={providerMode === "mock" ? "模拟生成结果" : "生成结果"} />{job?.result && job.state === "complete" && <DeleteImageButton key={job.result.id} id={job.result.id} onDelete={onDelete} />}</> : <div className="generation-preview-empty"><span className="empty-icon">⌁</span><strong>{job?.state === "complete" ? "图片已删除" : job ? "正在渲染本地结果…" : "生成的图像会显示在这里"}</strong><small>{job ? job.message : "提交提示词后将显示 native 生成结果。"}</small></div>}</div>}
    {tab === "metadata" && <div className="generation-preview-panel preview-metadata" role="tabpanel" aria-label={labels.metadata}>{metadata.length ? metadata.map(([key, value]) => <div className="preview-metadata-row" key={String(key)}><span>{String(key)}</span><strong>{formatMetadataValue(value)}</strong></div>) : <div className="generation-preview-empty"><strong>元数据尚不可用</strong><small>完成一次生成后显示真实请求与后端结果。</small></div>}</div>}
    {tab === "variants" && <div className="generation-preview-panel preview-variants" role="tabpanel" aria-label={labels.variants}>{results.length ? results.map((result, index) => result.result && <figure key={result.id}><img src={result.result.imageUrl} alt={`批量结果 ${index + 1}`} loading="lazy" decoding="async" /><figcaption>第 {index + 1} 张 · Seed {String(result.request.seed)}</figcaption><DeleteImageButton id={result.result.id} disabled={result.state !== "complete"} onDelete={onDelete} /></figure>) : <div className="generation-preview-empty"><strong>还没有变体</strong><small>批量生成的真实结果会显示在这里。</small></div>}</div>}
    <div className="preview-footer"><span>{job?.result?.metadata?.width ? `${formatMetadataValue(job.result.metadata.width)} × ${formatMetadataValue(job.result.metadata.height)}` : "— × —"}</span><span>PNG</span><span className={providerMode === "mock" ? "text-warning" : "text-success"}>{providerMode === "mock" ? "演示" : "Native 文件"}</span></div>
  </section>;
}

function GenerationInspector({ job, providerMode, queue }: { job: GenerationJob | null; providerMode: "mock" | "backend"; queue: QueueEntry[] }) {
  if (!job) return <aside className="surface-card generation-inspector"><div className="section-title">运行时检查器 <span className="truth-label truth-unavailable">等待中</span></div><div className="empty-state"><span className="empty-icon">◌</span><span>生成状态会显示在这里。</span></div><div className="inspector-note"><span className={`truth-label ${providerMode === "mock" ? "truth-demo" : "truth-unavailable"}`}>{providerMode === "mock" ? "演示" : "待预检"}</span><span>{providerMode === "mock" ? "模拟生命周期仅用于测试。" : "提交后由后端检查生成条件；硬件采样不代表推理已就绪。"}</span></div></aside>;
  return <aside className="surface-card generation-inspector"><div className="section-title">运行时检查器 <span className={`truth-label ${job.state === "complete" ? "truth-observed" : job.state === "failed" ? "truth-unavailable" : "truth-derived"}`}>{generationStatusLabel(job.state)}</span></div><div className="job-state" role={job.state === "failed" ? "alert" : undefined}><strong>{generationStatusLabel(job.state)}</strong><span>{job.error ?? job.message}</span></div><div className="progress-track" role="progressbar" aria-label="生成进度" aria-valuemin={0} aria-valuemax={100} aria-valuenow={job.progress}><span style={{ width: `${job.progress}%` }} /></div><div className="progress-reading"><span>当前任务</span><strong>{job.progress}%</strong></div><div className="inspector-grid"><span>后端</span><strong>{String(job.result?.metadata?.backend ?? "CUDA / stable-diffusion.cpp")}</strong><span>步数</span><strong>{job.request.steps}</strong><span>CFG</span><strong>{job.request.cfg}</strong><span>队列</span><strong>{queue.length ? `${queue.filter((entry) => entry.state === "complete").length}/${queue.length}` : "1/1"}</strong></div>{job.result ? <div className="result-wrap"><img src={job.result.imageUrl} alt={providerMode === "mock" ? "模拟生成结果详情" : "生成结果详情"} /><div className="result-caption"><span>结果已就绪</span><span className={`truth-label ${providerMode === "mock" ? "truth-demo" : "truth-observed"}`}>{providerMode === "mock" ? "演示数据" : "实时文件"}</span></div></div> : <div className="inspector-note"><span className="truth-label truth-derived">本地队列</span><span>正在轮询类型化提供方接口。</span></div>}</aside>;
}
