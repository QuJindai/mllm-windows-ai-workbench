import { useEffect, useState } from "react";
import type { ModelRecord } from "../../domain/models";
import { useDreamProvider } from "../providers";

const formatSize = (bytes: number) => `${(bytes / 1024 ** 3).toFixed(1)} GB`;

export function ModelsPage() {
  const provider = useDreamProvider();
  const [models, setModels] = useState<ModelRecord[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    void provider.listModels().then((items) => {
      if (!active) return;
      setModels(items);
      setSelectedId(items[0]?.id ?? null);
    }).catch((reason: unknown) => {
      if (active) setError(reason instanceof Error ? reason.message : "Unable to load model registry");
    }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [provider]);

  if (loading) return <section className="surface-card page-state" role="status">Loading models…</section>;
  if (error) return <section className="surface-card page-state" role="alert"><span className="truth-label truth-unavailable">ERROR</span>{error}</section>;
  if (models.length === 0) return <section className="surface-card page-state"><span className="empty-icon">▦</span><h2>No models found</h2><p className="muted-copy">Install a compatible checkpoint under E:\Dream to make it available.</p></section>;

  const selected = models.find((model) => model.id === selectedId) ?? models[0];
  return (
    <section className="models-layout">
      <div className="surface-card models-registry"><div className="card-head"><span>MODEL REGISTRY · {models.length} ITEMS</span><span className="truth-label truth-observed">OBSERVED</span></div><div className="model-grid">{models.map((model) => <ModelCard key={model.id} model={model} selected={model.id === selected.id} onSelect={() => setSelectedId(model.id)} />)}</div></div>
      <aside className="surface-card model-inspector"><div className="card-head"><span>INSPECTOR</span><span className={`truth-label ${selected.verified ? "truth-observed" : "truth-unavailable"}`}>{selected.verified ? "VERIFIED" : "UNAVAILABLE"}</span></div><h2>Model details</h2><div className="inspector-model-name">{selected.displayName}</div><div className="detail-grid"><span>Architecture</span><strong>{selected.architecture}</strong><span>Format</span><strong>{selected.format}</strong><span>Memory</span><strong>{formatSize(selected.sizeBytes)}</strong><span>Dream path</span><code>{selected.path}</code></div><div className="hash-box"><span>SHA-256</span><code>{selected.sha256 ?? "Unavailable"}</code></div><p className="muted-copy">{selected.description}</p></aside>
    </section>
  );
}

function ModelCard({ model, selected, onSelect }: { model: ModelRecord; selected: boolean; onSelect: () => void }) {
  return <button className={`model-card ${selected ? "is-selected" : ""}`} type="button" aria-pressed={selected} aria-label={`${model.displayName}, ${model.architecture}, ${model.format}`} onClick={onSelect}><img src={model.imageUrl} alt={`${model.displayName} preview`} /><div className="model-card-body"><div className="model-card-title"><strong>{model.displayName}</strong><span className="verified-mark">✓</span></div><div className="model-card-subtitle">{model.architecture} · {model.format}</div><div className="model-tags">{model.tags.slice(0, 3).map((tag) => <span key={tag}>{tag}</span>)}</div></div></button>;
}
