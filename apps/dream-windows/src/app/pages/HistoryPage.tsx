import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";
import type { HistoryItem } from "../../domain/history";
import { generationQualityWarning, MIN_GENERATION_STEPS } from "../../domain/generation-quality";
import { useDreamProvider } from "../providers";
import { TruthBadge } from "../components/TruthBadge";
import { useUiPreferences } from "../ui-preferences";
import { onImageDeleted } from "../image-deletion";
import { useImageDeletion } from "../image-deletion-state";

type Filter = "all" | "today" | "favorites" | "failed" | "tagged";
const HISTORY_PAGE_SIZE = 24;
export const HISTORY_POLL_INTERVAL_MS = 30000;

function historyQualityWarning(item: HistoryItem): string | null {
  const recommendedSteps = item.generationDefaults?.steps;
  return generationQualityWarning(
    item,
    recommendedSteps !== undefined && recommendedSteps < MIN_GENERATION_STEPS
      ? {
          minimumSteps: recommendedSteps,
          recommendedSteps,
          profileLabel: "当前模型按低步数蒸馏配置采样",
        }
      : undefined,
  );
}

function uniqueHistoryItems(items: HistoryItem[]) {
  const seen = new Set<string>();
  return items.filter((item) => {
    if (seen.has(item.id)) return false;
    seen.add(item.id);
    return true;
  });
}

export function HistoryPage({ onRerun }: { onRerun?: (item: HistoryItem) => void }) {
  const provider = useDreamProvider();
  const preferences = useUiPreferences();
  const [items, setItems] = useState<HistoryItem[]>([]);
  const [total, setTotal] = useState(0);
  const [viewerIndex, setViewerIndex] = useState(-1);
  const [filter, setFilter] = useState<Filter>("all");
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [paginationExhausted, setPaginationExhausted] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [compareOpen, setCompareOpen] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const selectedIdRef = useRef<string | null>(null);
  const itemsRef = useRef<HistoryItem[]>([]);
  const queryVersionRef = useRef(0);
  const nextPageRef = useRef(2);
  const deletedIdsRef = useRef(new Set<string>());
  const [deletionVersion, setDeletionVersion] = useState(0);
  const selectionAfterDeleteRef = useRef<string | null>(null);

  useEffect(() => onImageDeleted((id) => {
    deletedIdsRef.current.add(id);
    queryVersionRef.current += 1;
    setDeletionVersion((version) => version + 1);
    const previous = itemsRef.current;
    const nextItems = previous.filter((item) => item.id !== id);
    const previousIndex = previous.findIndex((item) => item.id === selectedIdRef.current);
    const preservedIndex = nextItems.findIndex((item) => item.id === selectedIdRef.current);
    const nextIndex = previousIndex < 0 ? -1 : preservedIndex >= 0 ? preservedIndex : Math.min(previousIndex, nextItems.length - 1);
    itemsRef.current = nextItems;
    selectedIdRef.current = nextItems[nextIndex]?.id ?? null;
    selectionAfterDeleteRef.current = selectedIdRef.current;
    setItems(nextItems);
    setViewerIndex(nextIndex);
    setTotal((count) => Math.max(0, count - (previous.length - nextItems.length)));
    setCompareOpen(false);
    setZoom(1);
    setPan({ x: 0, y: 0 });
  }), []);

  const selected = items[viewerIndex] ?? null;
  const deletion = useImageDeletion(provider, selected?.id ?? "");
  useEffect(() => { if (!loading) selectedIdRef.current = selected?.id ?? null; }, [selected?.id, loading]);

  const loadHistory = useCallback(async (preserveSelection: boolean, fallbackIndex = 0, queryVersion = queryVersionRef.current) => {
    try {
      const page = await provider.listHistory({ page: 1, pageSize: HISTORY_PAGE_SIZE, filter, search });
      if (queryVersion !== queryVersionRef.current) return;
      const previousId = preserveSelection ? selectedIdRef.current : null;
      const nextItems = uniqueHistoryItems(preserveSelection ? [...page.items, ...itemsRef.current] : page.items)
        .filter((item) => !deletedIdsRef.current.has(item.id));
      const preservedIndex = previousId ? nextItems.findIndex((item) => item.id === previousId) : -1;
      const nextIndex = nextItems.length === 0 ? -1 : preservedIndex >= 0 ? preservedIndex : Math.min(Math.max(0, fallbackIndex), nextItems.length - 1);
      if (!preserveSelection) {
        nextPageRef.current = page.page + 1;
        setPaginationExhausted(false);
      }
      itemsRef.current = nextItems;
      selectedIdRef.current = nextItems[nextIndex]?.id ?? null;
      setItems(nextItems);
      setTotal(page.total);
      setViewerIndex(nextIndex);
      setError(null);
    } catch (reason: unknown) {
      if (queryVersion !== queryVersionRef.current) return;
      setError(reason instanceof Error ? reason.message : "无法加载历史记录");
    }
  }, [filter, provider, search]);

  useEffect(() => {
    let active = true;
    let requestInFlight = true;
    const queryVersion = ++queryVersionRef.current;
    const selectedAfterDelete = selectionAfterDeleteRef.current;
    selectionAfterDeleteRef.current = null;
    nextPageRef.current = 2;
    itemsRef.current = [];
    selectedIdRef.current = selectedAfterDelete;
    setItems([]);
    setTotal(0);
    setViewerIndex(-1);
    setLoadingMore(false);
    setPaginationExhausted(false);
    setCompareOpen(false);
    setLoading(true);
    void loadHistory(!!selectedAfterDelete, 0, queryVersion).finally(() => {
      requestInFlight = false;
      if (active) setLoading(false);
    });
    const timer = window.setInterval(() => {
      if (!active || !preferences.historyAutoRefresh || document.visibilityState !== "visible" || requestInFlight) return;
      requestInFlight = true;
      void loadHistory(true, 0, queryVersion).finally(() => { requestInFlight = false; });
    }, preferences.historyInterval * 1000);
    return () => {
      active = false;
      if (queryVersionRef.current === queryVersion) queryVersionRef.current += 1;
      window.clearInterval(timer);
    };
  }, [loadHistory, preferences.historyAutoRefresh, preferences.historyInterval, deletionVersion]);

  const loadMore = async () => {
    const queryVersion = queryVersionRef.current;
    const pageNumber = nextPageRef.current;
    setLoadingMore(true);
    try {
      const page = await provider.listHistory({ page: pageNumber, pageSize: HISTORY_PAGE_SIZE, filter, search });
      if (queryVersion !== queryVersionRef.current) return;
      if (page.items.length === 0) {
        setPaginationExhausted(true);
        setTotal(page.total);
        setNotice("没有更多历史记录");
        setError(null);
        return;
      }
      const nextItems = uniqueHistoryItems([...itemsRef.current, ...page.items])
        .filter((item) => !deletedIdsRef.current.has(item.id));
      nextPageRef.current = page.page + 1;
      itemsRef.current = nextItems;
      setItems(nextItems);
      setTotal(page.total);
      setError(null);
    } catch (reason: unknown) {
      if (queryVersion !== queryVersionRef.current) return;
      setError(reason instanceof Error ? reason.message : "无法加载更多历史记录");
    } finally {
      if (queryVersion === queryVersionRef.current) setLoadingMore(false);
    }
  };

  const resetViewerTransform = () => { setZoom(1); setPan({ x: 0, y: 0 }); };
  const move = (delta: number) => {
    if (items.length === 0) return;
    const next = Math.max(0, Math.min(items.length - 1, (viewerIndex < 0 ? 0 : viewerIndex) + delta));
    selectedIdRef.current = items[next]?.id ?? null;
    setViewerIndex(next);
    resetViewerTransform();
    setCompareOpen(false);
  };
  const refresh = async (fallbackIndex = viewerIndex) => { await loadHistory(true, fallbackIndex); setNotice("历史记录已刷新"); };
  const deleteSelected = async () => {
    if (!selected) return;
    if (await deletion.remove((id) => provider.deleteHistory(id))) resetViewerTransform();
  };
  const confirmDelete = () => { if (selected && !deletion.busy && window.confirm(`确定删除“${selected.title}”的生成图片、修脸前原图和历史记录吗？文件移入本机删除暂存区，不删除人物档案或参考照片。`)) void deleteSelected(); };
  const toggleFavorite = async () => {
    if (!selected) return;
    try { await provider.favoriteHistory(selected.id, !selected.favorite); await loadHistory(true); }
    catch (reason: unknown) { setError(reason instanceof Error ? reason.message : "无法更新收藏状态"); }
  };

  useLayoutEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target;
      if (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement || target instanceof HTMLElement && target.isContentEditable) return;
      if (event.key === "ArrowRight") { event.preventDefault(); move(1); }
      if (event.key === "ArrowLeft") { event.preventDefault(); move(-1); }
      if (event.key === "Escape") { event.preventDefault(); setViewerIndex(-1); }
      if (event.key === "Delete") { event.preventDefault(); confirmDelete(); }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [items, selected, viewerIndex, deletion.busy]);

  if (loading) return <section className="surface-card page-state" role="status">正在加载历史记录…</section>;
  if (error && items.length === 0) return <section className="surface-card page-state" role="alert"><TruthBadge truth="unavailable" label="错误" />{error}</section>;

  const filterLabels: Record<Filter, string> = { all: `全部（${total}）`, today: "今天", favorites: "收藏", failed: "失败", tagged: "已标记" };
  const compareItems = selected && items.length > 1 ? [selected, items[(viewerIndex + 1) % items.length]] : items.slice(0, 2);
  return (
    <section className="history-workstation">
      <div className="history-main-column">
        <div className="history-toolbar prototype-history-toolbar">
          <div className="history-filters">{(["all", "today", "favorites", "failed", "tagged"] as Filter[]).map((value) => <button type="button" className={`filter-button ${filter === value ? "is-active" : ""}`} key={value} onClick={() => setFilter(value)}>{filterLabels[value]}</button>)}</div>
          <div className="history-toolbar-actions"><input className="history-search" aria-label="搜索历史记录" placeholder="搜索提示词、标签或模型…" value={search} onChange={(event) => setSearch(event.target.value)} /><button type="button" className="secondary-button" onClick={() => void refresh()}>刷新</button><button type="button" className="secondary-button" disabled={items.length < 2} onClick={() => setCompareOpen((open) => !open)}>比较当前两张</button></div>
        </div>
        {notice && <div className="inline-notice" role="status">{notice}</div>}
        {error && <div className="inline-error" role="alert">{error}</div>}
        {items.length === 0 ? <div className="surface-card empty-state history-empty"><span className="empty-icon">◷</span><span>没有符合条件的历史记录。</span></div> : <><div className="history-grid prototype-history-grid">{items.map((item, index) => <HistoryCard item={item} selected={index === viewerIndex} onSelect={() => { setViewerIndex(index); selectedIdRef.current = item.id; resetViewerTransform(); }} key={item.id} />)}</div>{items.length < total && !paginationExhausted && <div className="history-load-more"><button type="button" className="secondary-button" aria-label="加载更多历史记录" disabled={loadingMore} onClick={() => void loadMore()}>{loadingMore ? "正在加载…" : `加载更多（已加载 ${items.length} / ${total}）`}</button></div>}</>}
        {compareOpen && compareItems.length === 2 && <div className="surface-card compare-panel"><div className="compare-heading"><div><h2>并排比较</h2><p>同一历史列表中的相邻结果，参数仍以各自记录为准。</p></div><button type="button" className="secondary-button" onClick={() => setCompareOpen(false)}>关闭比较</button></div><div className="compare-grid">{compareItems.map((item, index) => <figure key={item.id}><img src={item.imageUrl} alt={`比较图 ${index + 1}`} loading="lazy" decoding="async" /><figcaption>{item.title}<small>{item.width} × {item.height} · {item.steps} 步</small></figcaption></figure>)}</div></div>}
      </div>
{deletion.error && <p role="alert" className="error-panel">{deletion.error}</p>}
      <HistoryViewer item={selected} providerMode={provider.mode} zoom={zoom} pan={pan} onZoomIn={() => setZoom((value) => Math.min(3, Number((value + 0.2).toFixed(1))))} onZoomOut={() => setZoom((value) => Math.max(1, Number((value - 0.2).toFixed(1))))} onResetZoom={resetViewerTransform} onPan={setPan} onPrevious={() => move(-1)} onNext={() => move(1)} onDelete={confirmDelete} onFavorite={() => void toggleFavorite()} onRerun={() => { if (selected && onRerun) onRerun(selected); else setNotice("已准备重新生成参数，请切换到生成页"); }} canPrevious={viewerIndex > 0} canNext={viewerIndex >= 0 && viewerIndex < items.length - 1} position={viewerIndex >= 0 ? `${viewerIndex + 1} / ${total}` : `0 / ${total}`} />
    </section>
  );
}

function HistoryCard({ item, selected, onSelect }: { item: HistoryItem; selected: boolean; onSelect: () => void }) {
  const qualityWarning = historyQualityWarning(item);
  return <button className={`history-card ${selected ? "is-selected" : ""}`} type="button" aria-pressed={selected} aria-label={`打开 ${item.title}`} onClick={onSelect}><img src={item.imageUrl} alt={`${item.title} 预览`} loading="lazy" decoding="async" /><span className="history-card-overlay"><strong>{item.title}</strong><span>{item.modelName}</span><span>{item.width} × {item.height} · {item.generationTimeMs ? `${(item.generationTimeMs / 1000).toFixed(1)} 秒` : "时间不可用"}</span></span>{qualityWarning && <span className="quality-risk" title={qualityWarning}>质量风险</span>}{item.favorite && <span className="favorite-mark" aria-label="已收藏">★</span>}{item.status === "failed" && <span className="failed-mark">失败</span>}</button>;
}

function HistoryViewer({ item, providerMode, zoom, pan, onZoomIn, onZoomOut, onResetZoom, onPan, onPrevious, onNext, onDelete, onFavorite, onRerun, canPrevious, canNext, position }: { item: HistoryItem | null; providerMode: "mock" | "backend"; zoom: number; pan: { x: number; y: number }; onZoomIn: () => void; onZoomOut: () => void; onResetZoom: () => void; onPan: React.Dispatch<React.SetStateAction<{ x: number; y: number }>>; onPrevious: () => void; onNext: () => void; onDelete: () => void; onFavorite: () => void; onRerun: () => void; canPrevious: boolean; canNext: boolean; position: string }) {
  const pointerStart = useRef<{ x: number; y: number } | null>(null);
  const provider = useDreamProvider();
  const deletion = useImageDeletion(provider, item?.id ?? "");
  if (!item) return <aside className="surface-card history-viewer"><div className="section-title">详情</div><div className="empty-state"><span className="empty-icon">◷</span><span>选择一个结果查看详情。</span></div><TruthBadge truth="unavailable" label="不可用" /></aside>;
  const qualityWarning = historyQualityWarning(item);
  const onPointerDown = (event: ReactPointerEvent<HTMLDivElement>) => { pointerStart.current = { x: event.clientX, y: event.clientY }; event.currentTarget.setPointerCapture?.(event.pointerId); };
  const onPointerUp = (event: ReactPointerEvent<HTMLDivElement>) => {
    const start = pointerStart.current;
    pointerStart.current = null;
    if (!start) return;
    const dx = event.clientX - start.x;
    const dy = event.clientY - start.y;
    if (zoom <= 1 && (!Number.isFinite(dx) || Math.abs(dx) >= 80 && Math.abs(dx) > Math.abs(dy))) { if (!Number.isFinite(dx) || dx < 0) { if (canNext) onNext(); } else if (canPrevious) onPrevious(); }
    else if (zoom > 1) onPan((current) => ({ x: current.x + dx, y: current.y + dy }));
  };
  return <aside className="surface-card history-viewer"><div className="inspector-title-row"><div className="section-title">详情</div><TruthBadge truth={providerMode === "mock" ? "demo" : "observed"} label={providerMode === "mock" ? "演示数据" : "实时文件"} /></div><div className="viewer-position">{position}</div><div className="history-viewer-stage" onPointerDown={onPointerDown} onPointerUp={onPointerUp}><img className="viewer-image" style={{ transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})` }} src={item.imageUrl} alt={`${item.title} 完整预览`} decoding="async" /></div><div className="viewer-zoom-controls"><button type="button" className="secondary-button" aria-label="缩小预览" onClick={onZoomOut}>−</button><span>缩放 {zoom.toFixed(1)}×</span><button type="button" className="secondary-button" aria-label="放大预览" onClick={onZoomIn}>＋</button><button type="button" className="secondary-button" aria-label="重置缩放" onClick={onResetZoom}>重置</button></div><h2>{item.title}</h2><div className="viewer-model">{item.modelName} · 随机种子 {item.seed}</div><div className="viewer-meta"><span>{item.width} × {item.height}</span><span>{item.steps} 步</span><span>{item.generationTimeMs ? `${(item.generationTimeMs / 1000).toFixed(1)} 秒` : "—"}</span></div>{qualityWarning && <div className="quality-warning" role="status">{qualityWarning}</div>}<p className="muted-copy">{item.prompt}</p><div className="viewer-actions"><button type="button" className="secondary-button" aria-label="上一个结果" disabled={!canPrevious} onClick={onPrevious}>←</button><button type="button" className="secondary-button" aria-label="下一个结果" disabled={!canNext} onClick={onNext}>→</button><button type="button" className="secondary-button" aria-label={item.favorite ? "取消收藏" : "收藏结果"} onClick={onFavorite}>{item.favorite ? "★" : "☆"}</button><button type="button" className="secondary-button" onClick={onRerun}>重新生成此图</button><button type="button" className="danger-button" aria-label="删除结果" disabled={deletion.busy} onClick={onDelete}>删除</button></div><div className="viewer-path"><span>文件</span><code>{item.filePath}</code></div></aside>;
}
