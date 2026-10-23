import { useEffect, useRef, useState } from "react";
import type { PointerEvent } from "react";
import type { RuntimeAttentionIndexAvailable, RuntimeAttentionMap } from "../../domain/trace";
import { useDreamProvider } from "../providers";
import { aggregateAttentionPeak, fullRegion, regionStatistics } from "../attention-analysis";
import type { AttentionRegion } from "../attention-analysis";

export function AttentionAnalysis({ index, map, onSelect }: { index: RuntimeAttentionIndexAvailable; map: RuntimeAttentionMap | null; onSelect: (id: string) => void }) {
  const provider = useDreamProvider();
  const [view, setView] = useState("aggregate");
  const [layer, setLayer] = useState("");
  const [search, setSearch] = useState("");
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const [region, setRegion] = useState<AttentionRegion>(fullRegion);
  const [opacity, setOpacity] = useState(.5);
  const [ranking, setRanking] = useState<Array<{ token: string; mean: number }>>([]);
  const [rankingMessage, setRankingMessage] = useState("");
  const [rankingRequest, setRankingRequest] = useState(0);
  const dragStart = useRef<{ x: number; y: number } | null>(null);
  const valuesCache = useRef(new Map<string, RuntimeAttentionMap>());
  const steps = [...new Set(index.maps.map((entry) => entry.step))].sort((a, b) => a - b);
  const tokens = index.tokens.filter((token) => !search || token.text.toLowerCase().includes(search.toLowerCase()));
  const statistics = map ? regionStatistics(map, region) : null;

  useEffect(() => {
    let active = true;
    setImageUrl(null);
    valuesCache.current.clear();
    void provider.getHistoryItem(index.runId).then((item) => { if (active) setImageUrl(item.imageUrl || null); }).catch(() => {});
    return () => { active = false; };
  }, [index.runId, provider]);

  useEffect(() => {
    if (map) {
      if (valuesCache.current.size >= 128) valuesCache.current.clear();
      valuesCache.current.set(`${map.runId}/${map.id}`, map);
    }
  }, [map]);

  useEffect(() => {
    setRanking([]);
    setRankingMessage("");
    if (!rankingRequest || !map) return;
    let active = true;
    const candidates = index.maps.filter((entry) => entry.step === map.step && entry.layerId === map.layerId);
    let cursor = 0;
    const rows: Array<{ token: string; mean: number }> = [];
    let failed = 0;
    setRankingMessage(`正在读取同层、同一步骤的 ${candidates.length} 个 Token…`);
    const worker = async () => {
      while (active && cursor < candidates.length) {
        const entry = candidates[cursor++];
        try {
          const key = `${index.runId}/${entry.id}`;
          const value = valuesCache.current.get(key) ?? await provider.getAttentionMap(index.runId, entry.id);
          if (!active) return;
          if (valuesCache.current.size >= 128) valuesCache.current.clear();
          valuesCache.current.set(key, value);
          const stats = regionStatistics(value, region);
          if (stats) rows.push({ token: index.tokens.find((token) => token.slot === entry.tokenSlot)?.text ?? String(entry.tokenSlot), mean: stats.mean });
        } catch { failed++; }
      }
    };
    void Promise.all([worker(), worker()]).then(() => {
      if (!active) return;
      setRanking(rows.sort((a, b) => b.mean - a.mean).slice(0, 5));
      setRankingMessage(`已比较 ${rows.length} / ${candidates.length} 个 Token${failed ? `，${failed} 个读取失败` : ""}。按区域原始注意力均值排序。`);
    });
    return () => { active = false; };
  }, [rankingRequest, map?.step, map?.layerId, index, provider, region]);

  const point = (event: PointerEvent<HTMLDivElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    return { x: Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width)), y: Math.min(1, Math.max(0, (event.clientY - rect.top) / rect.height)) };
  };
  const updateRegion = (value: AttentionRegion) => { setRankingRequest(0); setRegion(value); };
  const onPointerDown = (event: PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    dragStart.current = point(event);
  };
  const onPointerMove = (event: PointerEvent<HTMLDivElement>) => {
    const start = dragStart.current;
    if (!start) return;
    const end = point(event);
    updateRegion({ x: Math.min(start.x, end.x), y: Math.min(start.y, end.y), width: Math.max(.01, Math.abs(end.x - start.x)), height: Math.max(.01, Math.abs(end.y - start.y)) });
  };
  const range = map ? map.values.reduce((r, value) => ({ min: Math.min(r.min, value), max: Math.max(r.max, value) }), { min: Infinity, max: -Infinity }) : null;
  return <section className="surface-card h7-aggregate">
    <div className="notebook-tabs" role="tablist" aria-label="注意力分析方式">
      <button type="button" role="tab" aria-selected={view === "aggregate"} className={view === "aggregate" ? "is-active" : ""} onClick={() => setView("aggregate")}>聚合分析</button>
      <button type="button" role="tab" aria-selected={view === "region"} className={view === "region" ? "is-active" : ""} onClick={() => setView("region")}>图像叠加与区域</button>
    </div>
    {view === "aggregate" && <div role="tabpanel" aria-label="聚合分析">
      <div className="h7-map-controls"><label>筛选 Token<input aria-label="筛选注意力 Token" value={search} onChange={(event) => setSearch(event.target.value)} /></label><label>聚合层<select aria-label="聚合层" value={layer} onChange={(event) => setLayer(event.target.value)}><option value="">所有已采集层</option>{index.layers.map((entry) => <option key={entry.id} value={entry.id}>{entry.label}</option>)}</select></label></div>
      <p className="muted-copy">Token × 步骤：各已采集层的峰值注意力均值。点击色块查看对应的原始热力图；“—”表示未采集。</p>
      <div className="h7-matrix-scroll"><table className="h7-matrix"><thead><tr><th>Token / 步骤</th>{steps.map((step) => <th key={step}>{step + 1}</th>)}</tr></thead><tbody>{tokens.map((token) => <tr key={token.slot}><th>{token.text} <small>#{token.slot}</small></th>{steps.map((step) => {
        const peak = aggregateAttentionPeak(index.maps, token.slot, step, layer || undefined);
        const descriptor = index.maps.find((entry) => entry.tokenSlot === token.slot && entry.step === step && (!layer || entry.layerId === layer));
        return <td key={step}>{peak === null || !descriptor ? "—" : <button type="button" aria-label={`${token.text} 第 ${step + 1} 步 聚合峰值 ${peak.toFixed(4)}`} title={`峰值均值 ${peak.toFixed(4)}`} style={{ background: `hsl(${230 - Math.min(1, peak) * 230} 85% 35%)` }} onClick={() => onSelect(descriptor.id)}>{peak.toFixed(2)}</button>}</td>;
      })}</tr>)}</tbody></table></div>
      {map && <><h3>所选 Token 的逐层对比</h3><div className="h7-matrix-scroll"><table className="h7-matrix"><thead><tr><th>层 / 步骤</th>{steps.map((step) => <th key={step}>{step + 1}</th>)}</tr></thead><tbody>{index.layers.map((entry) => <tr key={entry.id}><th>{entry.label}</th>{steps.map((step) => {
        const descriptor = index.maps.find((value) => value.tokenSlot === map.tokenSlot && value.layerId === entry.id && value.step === step);
        return <td key={step}>{descriptor ? <button type="button" onClick={() => onSelect(descriptor.id)} title={`峰值 ${descriptor.peak.toFixed(4)}`} style={{ background: `hsl(${230 - Math.min(1, descriptor.peak) * 230} 85% 35%)` }}>{descriptor.peak.toFixed(2)}</button> : "—"}</td>;
      })}</tr>)}</tbody></table></div></>}
    </div>}
    {view === "region" && <div role="tabpanel" aria-label="图像叠加与区域">
      <p className="muted-copy">拖动框选区域，或用下方数字调整。叠加按注意力网格映射到原图，表示空间注意力分布，不是对象分割。</p>
      {map && range ? <>
        <label className="select-line">叠加透明度<input aria-label="叠加透明度" type="range" min="0" max="1" step="0.05" value={opacity} onChange={(event) => setOpacity(Number(event.target.value))} /></label>
        <div className="attention-overlay" onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={() => { dragStart.current = null; }} onPointerCancel={() => { dragStart.current = null; }} style={{ aspectRatio: imageUrl ? undefined : `${map.width} / ${map.height}` }}>
          {imageUrl && <img src={imageUrl} alt="本次生成的注意力叠加底图" draggable={false} onError={() => setImageUrl(null)} />}
          <div className="h7-heatmap" aria-label="区域注意力投影" style={{ gridTemplateColumns: `repeat(${map.width}, minmax(0, 1fr))`, gridTemplateRows: `repeat(${map.height}, minmax(0, 1fr))`, opacity: imageUrl ? opacity : 1 }}>{map.values.map((value, i) => <span key={i} style={{ background: `hsl(${230 - (range.max > range.min ? (value - range.min) / (range.max - range.min) : 0) * 230} 90% 50%)` }} />)}</div>
          <div className="attention-region" style={{ left: `${region.x * 100}%`, top: `${region.y * 100}%`, width: `${Math.min(region.width, 1 - region.x) * 100}%`, height: `${Math.min(region.height, 1 - region.y) * 100}%` }} />
        </div>
        {!imageUrl && <p className="muted-copy">对应输出图不可用，显示注意力网格。</p>}
        <div className="region-controls">{(["x", "y", "width", "height"] as const).map((key) => <label key={key}>{{ x: "区域左边（%）", y: "区域顶部（%）", width: "区域宽度（%）", height: "区域高度（%）" }[key]}<input type="number" min={key === "x" || key === "y" ? 0 : 1} max={key === "x" || key === "y" ? 99 : 100} value={Math.round(region[key] * 100)} onChange={(event) => {
          const value = Math.max(key === "x" || key === "y" ? 0 : .01, Math.min(key === "x" || key === "y" ? .99 : 1, Number(event.target.value) / 100));
          updateRegion({ ...region, [key]: value });
        }} /></label>)}</div>
        <div className="h7-stat-list"><div><span>区域平均注意力</span><strong>{statistics?.mean.toFixed(4) ?? "—"}</strong></div><div><span>区域峰值</span><strong>{statistics?.peak.toFixed(4) ?? "—"}</strong></div><div><span>参与统计网格</span><strong>{statistics?.count ?? "—"}</strong></div></div>
        <div className="json-actions"><button type="button" className="secondary-button" onClick={() => updateRegion(fullRegion)}>恢复全图</button><button type="button" className="secondary-button" onClick={() => setRankingRequest((value) => value + 1)}>比较区域 Top 5 Token</button></div>
        <p className="muted-copy" role="status">{rankingMessage}</p><ol className="token-ranking">{ranking.map((entry, i) => <li key={i}>{entry.token}<span>{entry.mean.toFixed(4)}</span></li>)}</ol>
      </> : <p className="muted-copy">请先选择一个已采集的 Token 热力图。</p>}
    </div>}
  </section>;
}
