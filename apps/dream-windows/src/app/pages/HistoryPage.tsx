import { useEffect, useState } from "react";
import type { HistoryItem } from "../../domain/history";
import { useDreamProvider } from "../providers";

type Filter = "all" | "today" | "favorites" | "failed" | "tagged";

export function HistoryPage() {
  const provider = useDreamProvider();
  const [items, setItems] = useState<HistoryItem[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = async (preferredIndex?: number) => {
    try {
      const page = await provider.listHistory({ page: 1, pageSize: 24, filter, search });
      setItems(page.items);
      setSelectedId((current) => {
        if (page.items.some((item) => item.id === current)) return current;
        if (page.items.length === 0) return null;
        return page.items[Math.min(preferredIndex ?? 0, page.items.length - 1)].id;
      });
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "Unable to load history");
    }
  };

  useEffect(() => {
    let active = true;
    setLoading(true);
    void provider.listHistory({ page: 1, pageSize: 24, filter, search }).then((page) => {
      if (!active) return;
      setItems(page.items);
      setSelectedId(page.items[0]?.id ?? null);
    }).catch((reason: unknown) => {
      if (active) setError(reason instanceof Error ? reason.message : "Unable to load history");
    }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [provider, filter, search]);

  const selectedIndex = items.findIndex((item) => item.id === selectedId);
  const selected = selectedIndex >= 0 ? items[selectedIndex] : null;
  const move = (delta: number) => {
    if (items.length === 0) return;
    const nextIndex = Math.max(0, Math.min(items.length - 1, (selectedIndex < 0 ? 0 : selectedIndex) + delta));
    setSelectedId(items[nextIndex].id);
  };

  const deleteSelected = async () => {
    if (!selected) return;
    const index = selectedIndex;
    await provider.deleteHistory(selected.id);
    await refresh(index);
  };

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "ArrowRight") move(1);
      if (event.key === "ArrowLeft") move(-1);
      if (event.key === "Delete") void deleteSelected();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  });

  const toggleFavorite = async () => {
    if (!selected) return;
    await provider.favoriteHistory(selected.id, !selected.favorite);
    await refresh(selectedIndex);
  };

  if (loading) return <section className="surface-card page-state" role="status">Loading history…</section>;
  if (error) return <section className="surface-card page-state" role="alert"><span className="truth-label truth-unavailable">ERROR</span>{error}</section>;

  return (
    <section className="history-layout">
      <div className="surface-card history-registry">
        <div className="history-toolbar"><div><div className="card-head"><span>HISTORY GRID · {items.length} RESULTS</span><span className="truth-label truth-demo">MOCK DATA</span></div><div className="filter-row">{(["all", "today", "favorites", "failed", "tagged"] as Filter[]).map((value) => <button type="button" className={`filter-button ${filter === value ? "is-active" : ""}`} key={value} onClick={() => setFilter(value)}>{value}</button>)}</div></div><input className="history-search" aria-label="Search history" placeholder="Search history" value={search} onChange={(event) => setSearch(event.target.value)} /></div>
        {items.length === 0 ? <div className="empty-state history-empty"><span className="empty-icon">◷</span><span>No history matches this query.</span></div> : <div className="history-grid">{items.map((item) => <HistoryCard item={item} selected={item.id === selectedId} onSelect={() => setSelectedId(item.id)} key={item.id} />)}</div>}
      </div>
      <HistoryViewer item={selected} onPrevious={() => move(-1)} onNext={() => move(1)} onDelete={() => void deleteSelected()} onFavorite={() => void toggleFavorite()} canPrevious={selectedIndex > 0} canNext={selectedIndex >= 0 && selectedIndex < items.length - 1} />
    </section>
  );
}

function HistoryCard({ item, selected, onSelect }: { item: HistoryItem; selected: boolean; onSelect: () => void }) {
  return <button className={`history-card ${selected ? "is-selected" : ""}`} type="button" aria-pressed={selected} aria-label={`Open ${item.title}`} onClick={onSelect}><img src={item.imageUrl} alt={`${item.title} preview`} /><span className="history-card-overlay"><strong>{item.title}</strong><span>{item.modelName}</span></span>{item.favorite && <span className="favorite-mark" aria-label="Favorite">★</span>}{item.status === "failed" && <span className="failed-mark">FAILED</span>}</button>;
}

function HistoryViewer({ item, onPrevious, onNext, onDelete, onFavorite, canPrevious, canNext }: { item: HistoryItem | null; onPrevious: () => void; onNext: () => void; onDelete: () => void; onFavorite: () => void; canPrevious: boolean; canNext: boolean }) {
  if (!item) return <aside className="surface-card history-viewer"><div className="card-kicker">HISTORY VIEWER</div><div className="empty-state"><span className="empty-icon">◷</span><span>Select a result to inspect it.</span></div><span className="truth-label truth-unavailable">UNAVAILABLE</span></aside>;
  return <aside className="surface-card history-viewer"><div className="card-head"><span>HISTORY VIEWER</span><span className={`truth-label ${item.status === "failed" ? "truth-unavailable" : "truth-demo"}`}>{item.status === "failed" ? "FAILED" : "DEMO DATA"}</span></div><img className="viewer-image" src={item.imageUrl} alt={`${item.title} full preview`} /><h2>{item.title}</h2><div className="viewer-model">{item.modelName} · seed {item.seed}</div><p className="muted-copy">{item.prompt}</p><div className="viewer-meta"><span>{item.width} × {item.height}</span><span>{item.steps} steps</span><span>{item.generationTimeMs} ms</span></div><div className="viewer-actions"><button type="button" className="secondary-button" aria-label="Previous result" disabled={!canPrevious} onClick={onPrevious}>←</button><button type="button" className="secondary-button" aria-label="Next result" disabled={!canNext} onClick={onNext}>→</button><button type="button" className="secondary-button" aria-label={item.favorite ? "Unfavorite result" : "Favorite result"} onClick={onFavorite}>{item.favorite ? "★" : "☆"}</button><button type="button" className="danger-button" aria-label="Delete result" onClick={onDelete}>Delete</button></div><div className="viewer-path"><span>File</span><code>{item.filePath}</code></div></aside>;
}
