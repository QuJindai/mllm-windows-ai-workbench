import { useEffect, useState } from "react";
import type { Experiment, ExperimentVariant } from "../../domain/experiment";
import type { ResearchStatus, RuntimeCapabilities } from "../../domain/trace";
import { TruthBadge } from "../components/TruthBadge";
import { useDreamProvider } from "../providers";
import { MobileFusionExperiment } from "../components/research/MobileFusionExperiment";
import { ResearchImageExperiment } from "../components/research/ResearchImageExperiment";

const defaultPrompt = "a serene mountain lake at sunrise, cinematic lighting, ultra detailed, photorealistic, 8k, dramatic clouds, reflection on water, adventure photography";
const defaultNegativePrompt = "low quality, blurry, cartoon, anime, text, watermark, deformed, extra limbs, bad anatomy, lowres";
const variantLabels: Record<string, string> = { Baseline: "完整提示词（控制组）", "Equal Mean": "平衡描述改写", "First Only": "仅首段提示词", "Token Weighted": "重点描述改写" };
const variantDescriptions: Record<string, string> = {
  Baseline: "原始提示词控制组",
  "Equal Mean": "纯文本平衡描述改写",
  "First Only": "仅保留首段提示词",
  "Token Weighted": "纯文本重点描述改写",
  "完整提示词（控制组）": "原始提示词控制组",
  "平衡描述改写": "纯文本平衡描述改写",
  "仅首段提示词": "仅保留首段提示词",
  "重点描述改写": "纯文本重点描述改写",
};
const variantStateLabels: Record<NonNullable<ExperimentVariant["state"]>, string> = {
  queued: "排队中",
  preparing: "准备中",
  sampling: "生成中",
  decoding: "解码中",
  complete: "已完成",
  failed: "失败",
  cancelled: "已取消",
};

export function LabPage({ onPromote }: { onPromote?: (request: { prompt: string; negativePrompt: string; modelId: string; steps: number; cfg: number; seed: number }) => void } = {}) {
  const provider = useDreamProvider();
  const [capabilities, setCapabilities] = useState<RuntimeCapabilities | null>(null);
  const [researchStatus, setResearchStatus] = useState<ResearchStatus | null>(null);
  const [models, setModels] = useState<Array<{ id: string; displayName: string }>>([]);
  const [notebookTab, setNotebookTab] = useState<"notes" | "metadata" | "comparisons">("notes");
  const [kind, setKind] = useState<"fusion" | "steps" | "model">("fusion");
  const [modelId, setModelId] = useState("cyberrealistic-xl-v10-standard");
  const [prompt, setPrompt] = useState(defaultPrompt);
  const [negativePrompt, setNegativePrompt] = useState(defaultNegativePrompt);
  const [seed, setSeed] = useState("20260906");
  const [steps, setSteps] = useState("20");
  const [cfg, setCfg] = useState("4");
  const [experiment, setExperiment] = useState<Experiment | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    void Promise.all([provider.getCapabilities(), provider.getResearchStatus()]).then(([nextCapabilities, nextResearch]) => {
      if (!active) return;
      setCapabilities(nextCapabilities);
      setResearchStatus(nextResearch);
    }).catch((reason: unknown) => { if (active) setError(reason instanceof Error ? reason.message : "无法读取实验能力"); });
    void provider.listModels().then((items) => {
      if (!active) return;
      const readyModels = items.filter((item) => item.status === "ready");
      setModels(readyModels.map((item) => ({ id: item.id, displayName: item.displayName })));
      setModelId((current) => readyModels.some((item) => item.id === current) ? current : readyModels[0]?.id ?? current);
    }).catch(() => {
      // Model loading errors are reported by the Models page; keep the editable ID
      // here so a configured backend can still accept a manually entered model ID.
    });
    return () => { active = false; };
  }, [provider]);

  useEffect(() => {
    if (!experiment || experiment.status === "complete" || experiment.status === "failed") return;
    let active = true;
    let timer: number | undefined;
    const scheduleNext = () => {
      if (active) timer = window.setTimeout(() => void poll(), 1000);
    };
    const poll = async () => {
      if (!active) return;
      try {
        const next = await provider.getExperiment(experiment.id);
        if (!active) return;
        setExperiment(next);
        setError(null);
        if (next.status !== "complete" && next.status !== "failed") scheduleNext();
      } catch (reason: unknown) {
        if (!active) return;
        setError(reason instanceof Error ? reason.message : "无法读取实验进度");
        scheduleNext();
      }
    };
    scheduleNext();
    return () => {
      active = false;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [experiment?.id, provider]);

  const modelComparisonAvailable = models.length >= 2;
  const canRun = (provider.mode === "mock" || capabilities?.semanticExperiments.available === true) && (kind !== "model" || modelComparisonAvailable);
  const experimentActive = Boolean(experiment && experiment.status !== "complete" && experiment.status !== "failed");
  const runExperiment = async () => {
    if (running || experimentActive) return;
    const parsedSeed = Number(seed);
    if (!Number.isInteger(parsedSeed) || parsedSeed < 0) { setError("随机种子必须是非负整数"); return; }
    setRunning(true); setError(null); setExperiment(null);
    try {
      const result = await provider.runExperiment({ kind, seed: parsedSeed, modelId, prompt, negativePrompt, steps: Number(steps), cfg: Number(cfg) });
      setExperiment(result);
    } catch (reason: unknown) { setError(reason instanceof Error ? reason.message : "实验运行失败"); }
    finally { setRunning(false); }
  };

  return (
    <section className="lab-layout">
      <div className="lab-main">
        <ResearchImageExperiment />
        <MobileFusionExperiment />
        <div className="surface-card lab-controls">
          <div className="section-title">语义实验控制 <span className="truth-label truth-derived">同一随机种子 · 受控对照</span></div>
          <div className="lab-control-grid">
            <label>实验类型<select aria-label="实验类型" value={kind} onChange={(event) => setKind(event.target.value as typeof kind)}><option value="fusion">提示词层对照</option><option value="steps">步数对照</option><option value="model" disabled={!modelComparisonAvailable}>模型对照（需要至少两个可用模型）</option></select></label>
            <label>模型{models.length > 0 ? <select aria-label="实验模型" value={modelId} onChange={(event) => setModelId(event.target.value)}>{models.map((model) => <option value={model.id} key={model.id}>{model.displayName}</option>)}</select> : <input aria-label="实验模型" value={modelId} onChange={(event) => setModelId(event.target.value)} />}</label>
            <label>随机种子（锁定）<input aria-label="随机种子（锁定）" inputMode="numeric" value={seed} onChange={(event) => setSeed(event.target.value)} /></label>
            <label>步数<select aria-label="步数" value={steps} onChange={(event) => setSteps(event.target.value)}><option value="20">20</option><option value="28">28</option><option value="50">50</option></select></label>
            <label>CFG 缩放<select aria-label="CFG 缩放" value={cfg} onChange={(event) => setCfg(event.target.value)}><option value="4">4（标准版平衡）</option><option value="5.5">5.5</option><option value="7">7</option></select></label>
            <label>比较策略<select aria-label="比较策略" value={kind === "fusion" ? "fusion" : kind} onChange={(event) => setKind(event.target.value as typeof kind)}><option value="fusion">提示词文本改写对照</option><option value="steps">固定步数阶梯</option><option value="model" disabled={!modelComparisonAvailable}>模型对照：固定随机种子（需要至少两个可用模型）</option></select></label>
          </div>
          <div className="lab-prompt-grid"><label>提示词<textarea aria-label="实验提示词" value={prompt} onChange={(event) => setPrompt(event.target.value)} rows={3} /></label><label>负面提示词<textarea aria-label="实验负面提示词" value={negativePrompt} onChange={(event) => setNegativePrompt(event.target.value)} rows={3} /></label></div>
          <div className="inline-notice" role="status">{kind === "model" && !modelComparisonAvailable ? `模型对照不可用：当前检测到 ${models.length} 个可用模型，需要至少 2 个` : canRun ? (provider.mode === "mock" ? "演示提供方已就绪：用于验证交互链路" : "语义实验已连接生产生成队列") : `语义实验能力不可用：${capabilities?.semanticExperiments.message ?? "未检测到可用的原生生成依赖，不会伪造对照结果"}`}{researchStatus?.available === false && <span>　· H7 研究引擎仍不可用</span>}</div>
          {error && <div className="inline-error" role="alert">{error}</div>}
          <button className="primary-button" type="button" disabled={!canRun || running || experimentActive} onClick={() => void runExperiment()}>{running || experimentActive ? "实验运行中…" : "运行实验"}</button>
        </div>

        {experiment && <div className="inline-notice experiment-status" role="status">实验{experiment.status === "complete" ? "完成" : experiment.status === "failed" ? "失败" : experiment.status === "queued" ? "排队中" : "进行中"}：{experiment.message ?? "已返回实验记录"}　· 实验 ID {experiment.id}</div>}
        <div className="lab-variant-grid">{(experiment?.variants ?? placeholderVariants).map((variant, index) => <VariantCard key={variant.id ?? `${variant.label}-${index}`} variant={variant} index={index} experimentReady={Boolean(experiment)} />)}</div>
      </div>
      <aside className="surface-card notebook">
        <div className="section-title">实验记录本 <span className="collapse-mark">⌃</span></div>
        <div className="notebook-tabs" role="tablist" aria-label="实验记录本">
          <button className={notebookTab === "notes" ? "is-active" : ""} type="button" role="tab" aria-selected={notebookTab === "notes"} onClick={() => setNotebookTab("notes")}>笔记</button>
          <button className={notebookTab === "metadata" ? "is-active" : ""} type="button" role="tab" aria-selected={notebookTab === "metadata"} onClick={() => setNotebookTab("metadata")}>元数据</button>
          <button className={notebookTab === "comparisons" ? "is-active" : ""} type="button" role="tab" aria-selected={notebookTab === "comparisons"} onClick={() => setNotebookTab("comparisons")}>对比</button>
        </div>
        {notebookTab === "notes" && <div role="tabpanel"><label>实验标题<input aria-label="实验标题" defaultValue="提示词层改写对照——同一随机种子研究" /></label><label>观察记录<textarea defaultValue="每个变体锁定同一随机种子；提示词和模型是否锁定取决于实验类型。只记录提供方实际返回的图像与指标。" rows={4} /></label><label>结论<textarea defaultValue="在真实实验输出和指标可用前，不报告结论。" rows={3} /></label><div className="notebook-footer"><TruthBadge truth={!experiment ? "unavailable" : provider.mode === "mock" ? "demo" : "observed"} label={!experiment ? "等待实验" : provider.mode === "mock" ? "演示数据" : "实测数据"} /><button className="primary-button" type="button" disabled={!experiment || !onPromote} onClick={() => onPromote?.({ prompt, negativePrompt, modelId, steps: Number(steps), cfg: Number(cfg), seed: Number(seed) })}>提升为生成预设</button></div></div>}
        {notebookTab === "metadata" && <div className="notebook-empty" role="tabpanel">{experiment ? <><strong>实验元数据</strong><p>实验 ID：{experiment.id}<br />随机种子：{experiment.seed}<br />锁定字段：{experiment.lockedFields.join("、")}</p></> : <><strong>实验元数据不可用</strong><p>运行实验后，这里显示实际请求身份。</p></>}</div>}
        {notebookTab === "comparisons" && <div className="notebook-empty" role="tabpanel">{experiment ? <><strong>对比输出</strong><p>已返回 {experiment.variants.length} 个变体；图像和指标来自实验提供方。</p></> : <><strong>对比输出不可用</strong><p>运行实验后，这里显示对比结果。</p></>}</div>}
      </aside>
    </section>
  );
}

type DisplayVariant = Omit<ExperimentVariant, "modelId"> & { modelId?: string };

const placeholderVariants: DisplayVariant[] = ["完整提示词（控制组）", "平衡描述改写", "仅首段提示词", "重点描述改写"].map((label, index) => ({ id: `placeholder-${index}`, label }));

function VariantCard({ variant, index, experimentReady }: { variant: DisplayVariant; index: number; experimentReady: boolean }) {
  const label = variantLabels[variant.label] ?? variant.label;
  const description = variantDescriptions[variant.label] ?? "受控对比变体";
  const state = variant.error ? "失败" : variant.state ? variantStateLabels[variant.state] : experimentReady ? "状态未返回" : "等待中";
  const emptyMessage = variant.error ?? (variant.state === "queued" ? "等待生成队列" : variant.state === "preparing" ? "正在准备原生生成" : variant.state === "sampling" ? "正在生成图像" : variant.state === "decoding" ? "正在解码图像" : variant.state === "complete" ? "生成完成但未返回图像" : experimentReady ? "图像未返回" : "等待运行实验");
  const metric = variant.metric === undefined ? "不可用（后端未返回）" : `${variant.metric.toFixed(2)}（后端返回）`;
  return <article className="surface-card variant-card"><div className="variant-title"><span className="variant-number">{index + 1}</span><div><h2>{label}</h2><p>{description}</p></div></div>{variant.imageUrl ? <img className="variant-image" src={variant.imageUrl} alt={`${label} 实验结果`} loading="lazy" decoding="async" /> : <div className="variant-empty"><span>{emptyMessage}</span></div>}<div className="variant-meta"><span>状态 <strong>{state}</strong></span><span>指标 <strong>{metric}</strong></span><span>实际模型 <strong>{variant.modelId ?? (experimentReady ? "未返回" : "等待实验")}</strong></span><span>变体 ID <strong>{variant.jobId ?? variant.id}</strong></span></div></article>;
}
