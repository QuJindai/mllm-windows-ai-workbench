import { useEffect, useMemo, useState } from "react";
import type { ModelRecord } from "../../domain/models";
import { useDreamProvider } from "../providers";
import { TruthBadge } from "../components/TruthBadge";

const formatSize = (bytes: number) => bytes > 0 ? `${(bytes / 1024 ** 3).toFixed(2)} GB` : "—";
type ModelFilter = "all" | "checkpoint" | "lora" | "vae" | "embedding";
const filterLabels: Record<ModelFilter, string> = { all: "全部", checkpoint: "Checkpoint", lora: "LoRA", vae: "VAE", embedding: "Embedding" };
const kindLabels: Record<string, string> = { checkpoint: "Checkpoint", lora: "LoRA", vae: "VAE", embedding: "Embedding" };

export function ModelsPage() {
  const provider = useDreamProvider();
  const [models, setModels] = useState<ModelRecord[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [filter, setFilter] = useState<ModelFilter>("all");
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const loadModels = async (keepSelection = false) => {
    setLoading(true);
    try {
      const items = await provider.listModels();
      setModels(items);
      setSelectedId((current) => keepSelection && items.some((item) => item.id === current) ? current : items[0]?.id ?? null);
      setError(null);
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "无法加载模型索引");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void loadModels(); }, [provider]);

  const visibleModels = useMemo(() => models.filter((model) => {
    const needle = search.trim().toLowerCase();
    const matchesFilter = filter === "all" || model.kind.toLowerCase() === filter;
    const matchesSearch = !needle || [model.displayName, model.architecture, model.format, model.path, ...model.tags].join(" ").toLowerCase().includes(needle);
    return matchesFilter && matchesSearch;
  }), [filter, models, search]);
  const selected = models.find((model) => model.id === selectedId) ?? visibleModels[0] ?? models[0];

  const verify = async () => {
    if (!selected) return;
    setWorking(true);
    try {
      const result = await provider.verifyModel(selected.id);
      setModels((current) => current.map((item) => item.id === result.id ? result : item));
      setNotice(result.verified ? "模型身份已验证" : "模型身份无法验证");
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "无法验证模型");
    } finally {
      setWorking(false);
    }
  };

  const reindex = async () => {
    setWorking(true);
    try {
      const items = await provider.reindexModels();
      setModels(items);
      setNotice(`模型索引已刷新 · ${items.length} 个模型`);
      setError(null);
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "无法重建模型索引");
    } finally {
      setWorking(false);
    }
  };

  const openModelsFolder = async () => {
    setWorking(true);
    try {
      const result = await provider.openWorkspace("models");
      setNotice(result.opened ? `已打开 ${result.path}` : "无法打开模型目录");
      setError(null);
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "无法打开模型目录");
    } finally {
      setWorking(false);
    }
  };

  if (loading) return <section className="surface-card page-state" role="status">正在加载模型…</section>;
  if (error && models.length === 0) return <section className="surface-card page-state" role="alert"><TruthBadge truth="unavailable" label="错误" />{error}</section>;
  if (models.length === 0) return <section className="surface-card page-state"><span className="empty-icon">▦</span><h2>未找到模型</h2><p className="muted-copy">将兼容的 Checkpoint 放入 E:\Dream\models 后即可使用。</p><div className="empty-state-actions"><button className="primary-button" type="button" onClick={() => void openModelsFolder()} disabled={working}>{working ? "打开中…" : "打开模型目录"}</button><button className="secondary-button" type="button" onClick={() => void reindex()} disabled={working}>{working ? "扫描中…" : "重新扫描"}</button></div>{notice && <div className="inline-notice" role="status">{notice}</div>}{error && <div className="inline-error" role="alert">{error}</div>}</section>;

  return (
    <section className="models-workstation">
      <div className="models-main-column">
        <div className="surface-card model-storage-card"><div><span className="model-storage-icon">⌂</span><div><strong>E:\Dream 模型</strong><small>本地模型索引</small></div></div><div className="storage-reading"><span>已索引</span><strong>{models.length} 个模型</strong></div><button className="secondary-button" type="button" onClick={() => void reindex()} disabled={working}>{working ? "刷新中…" : "重建索引"}</button></div>
        <div className="model-toolbar"><div className="model-search-wrap"><span>⌕</span><input aria-label="搜索模型" placeholder="搜索模型、标签或文件名…" value={search} onChange={(event) => setSearch(event.target.value)} /></div><div className="model-filters">{(["all", "checkpoint", "lora", "vae", "embedding"] as ModelFilter[]).map((value) => <button type="button" key={value} className={filter === value ? "is-active" : ""} onClick={() => setFilter(value)}>{filterLabels[value]}</button>)}</div></div>
        {notice && <div className="inline-notice" role="status">{notice}</div>}
        {error && <div className="inline-error" role="alert">{error}</div>}
        <div className="model-grid prototype-model-grid">{visibleModels.map((model) => <ModelCard key={model.id} model={model} selected={model.id === selected?.id} onSelect={() => setSelectedId(model.id)} />)}</div>
        {visibleModels.length === 0 && <div className="surface-card page-state"><span className="empty-icon">⌕</span><p>没有符合筛选条件的模型。</p></div>}
      </div>
      {selected && <aside className="surface-card model-inspector prototype-model-inspector"><div className="inspector-title-row"><div className="section-title">模型检查器</div><TruthBadge truth={selected.verified ? "observed" : "unavailable"} label={selected.verified ? "已验证" : "不可用"} /></div><div className="inspector-preview">{selected.imageUrl ? <img src={selected.imageUrl} alt={`${selected.displayName} 预览`} /> : <div className="preview-placeholder"><span>◈</span><small>暂无预览资源</small></div>}</div><h2>模型详情</h2><div className="inspector-model-name">{selected.displayName}</div><div className="detail-grid"><span>类型</span><strong>{kindLabels[selected.kind] ?? selected.kind}</strong><span>架构</span><strong>{selected.architecture}</strong><span>格式</span><strong>{selected.format}</strong><span>文件大小</span><strong>{formatSize(selected.sizeBytes)}</strong><span>Dream 路径</span><code>{selected.path}</code></div><div className="hash-box"><span>SHA-256</span><code>{selected.sha256 ?? "不可用"}</code></div><p className="muted-copy">{selected.description}</p><div className="inspector-actions"><button className="primary-button" type="button" onClick={verify} disabled={working}>{working ? "验证中…" : "验证 SHA"}</button><button className="secondary-button" type="button" onClick={() => void openModelsFolder()} disabled={working}>{working ? "打开中…" : "打开模型目录"}</button></div><p className="muted-copy">将模型文件放入 E:\Dream\models 后点击“重建索引”。</p></aside>}
    </section>
  );
}

function ModelCard({ model, selected, onSelect }: { model: ModelRecord; selected: boolean; onSelect: () => void }) {
  return <button className={`model-card prototype-model-card ${selected ? "is-selected" : ""}`} type="button" aria-pressed={selected} aria-label={`打开 ${model.displayName}，${model.architecture}，${model.format}`} onClick={onSelect}><div className="model-card-image">{model.imageUrl ? <img src={model.imageUrl} alt={`${model.displayName} 预览`} /> : <div className="preview-placeholder"><span>◈</span><small>GGUF</small></div>}<span className="model-type-chip">{kindLabels[model.kind] ?? model.kind}</span></div><div className="model-card-body"><div className="model-card-title"><strong>{model.displayName}</strong><span className={`verified-mark ${model.verified ? "is-verified" : "is-unverified"}`} aria-label={model.verified ? "已验证" : "未验证"}>{model.verified ? "✓" : "!"}</span></div><div className="model-card-subtitle">{model.architecture} · {model.format} · {formatSize(model.sizeBytes)}</div><div className="model-card-status">{model.status === "ready" ? "可进行本地生成" : model.status}</div>{model.error && <div role="alert" className="model-error">{model.error}</div>}</div></button>;
}
