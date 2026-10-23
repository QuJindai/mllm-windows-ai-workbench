import { useEffect, useState } from "react";
import type { RuntimeSelfAttentionIndex, RuntimeSelfAttentionMap, RuntimeSelfAttentionMapDescriptor } from "../../domain/trace";
import { useDreamProvider } from "../providers";
import { JsonViewer } from "./JsonViewer";
import { RawMetric, ResearchSpatialMap, researchMessage } from "./ResearchArtifactView";

export function SelfAttentionPanel({ runId }: { runId: string | null }) {
  const provider = useDreamProvider();
  const [index, setIndex] = useState<RuntimeSelfAttentionIndex | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [map, setMap] = useState<RuntimeSelfAttentionMap | null>(null);
  const [indexMessage, setIndexMessage] = useState("正在读取自注意力索引…");
  const [mapMessage, setMapMessage] = useState("正在读取所选空间图…");
  const available = index?.available && index.runId === runId ? index : null;
  const descriptor = available?.maps.find((entry) => entry.id === selectedId) ?? available?.maps[0];

  useEffect(() => {
    let active = true;
    setIndex(null);
    setSelectedId(null);
    setMap(null);
    setIndexMessage(runId ? "正在读取自注意力索引…" : "等待包含运行 ID 的原生记录…");
    if (runId) void provider.getSelfAttentionIndex(runId).then((value) => {
      if (!active) return;
      setIndex(value);
      if (!value.available) setIndexMessage(researchMessage(value.message));
    }).catch(() => { if (active) setIndexMessage("自注意力索引读取失败，请刷新记录。"); });
    return () => { active = false; };
  }, [provider, runId]);

  useEffect(() => {
    let active = true;
    setMap(null);
    setMapMessage("正在读取所选空间图…");
    if (runId && descriptor) void provider.getSelfAttentionMap(runId, descriptor.id).then((value) => {
      if (!active) return;
      if (!value.available) { setMapMessage(researchMessage(value.message)); return; }
      const fields = ["id", "step", "layerId", "queryIndex", "queryX", "queryY", "width", "height", "entropy", "peak", "coverage"] as const;
      if (value.runId !== runId || fields.some((key) => value[key] !== descriptor[key])) {
        setMapMessage("自注意力空间图与所选索引不一致，已停止显示该图。");
        return;
      }
      setMap(value);
    }).catch(() => { if (active) setMapMessage("自注意力空间图读取失败，请刷新记录。"); });
    return () => { active = false; };
  }, [provider, runId, descriptor]);

  const selectedMap = map?.runId === runId && map?.id === descriptor?.id ? map : null;
  const select = (predicate: (entry: RuntimeSelfAttentionMapDescriptor) => boolean, prefer: (entry: RuntimeSelfAttentionMapDescriptor) => boolean) => {
    const entry = available?.maps.find((entry) => predicate(entry) && prefer(entry)) ?? available?.maps.find(predicate);
    if (entry) setSelectedId(entry.id);
  };
  const layerMaps = available?.maps.filter((entry) => entry.layerId === descriptor?.layerId) ?? [];
  const steps = [...new Set(layerMaps.map((entry) => entry.step))].sort((a, b) => a - b);
  const anchors = layerMaps.filter((entry) => entry.step === descriptor?.step).sort((a, b) => a.queryIndex - b.queryIndex);
  return <section className="surface-card research-artifact-panel">
    <div className="section-title">H7 自注意力 <span className={`truth-label ${available ? "truth-observed" : "truth-unavailable"}`}>{available ? "索引 · 实测" : "张量不可用"}</span></div>
    <p className="research-banner">H7 同时采集条件影响、潜空间和 Self/Cross 注意力，增加研究前向计算、概率归约和文件写入开销。这里按需读取一张空间图，研究耗时不代表基础生成性能。</p>
    <p>{available?.source === "diffusers-unet" ? "人物引擎：从实测 Q/K 以 FP32 softmax 重算条件分支概率，再对多头取均值；是派生观察，不是底层融合算子的逐位转储。" : "从查询锚点观察同层空间位置之间的注意力：显示原始多头均值 softmax 概率，颜色仅用于显示。"}白框是查询位置，不是对象轮廓或贡献占比。</p>
    <p className="muted-copy">{available?.source === "diffusers-unet" ? `当前采集 ${available.layers.length} 层、${new Set(available.maps.map(entry => entry.step)).size} 步；每层最多 9 个空间锚点。扩展采集仍不是完整 N×N 或逐头转储。` : "最多 3 个代表层、5 个采样步骤、每层 9 个固定空间锚点；总计不超过 512 张图，每图不超过 128 × 128。只列出实际采集的组合。"}</p>
    {available && descriptor ? <>
      <p>运行：{available.runId} · {available.maps.length} 张实测图 · 来源：{available.source}</p>
      <div className="h7-map-controls research-self-controls">
        <label>代表层<select aria-label="自注意力层" value={descriptor.layerId} onChange={(event) => select((entry) => entry.layerId === event.target.value, (entry) => entry.step === descriptor.step && entry.queryIndex === descriptor.queryIndex)}>{available.layers.filter((layer) => available.maps.some((entry) => entry.layerId === layer.id)).map((layer) => <option key={layer.id} value={layer.id}>{layer.label}</option>)}</select></label>
        <label>采样步骤<select aria-label="自注意力步骤" value={descriptor.step} onChange={(event) => select((entry) => entry.layerId === descriptor.layerId && entry.step === Number(event.target.value), (entry) => entry.queryIndex === descriptor.queryIndex)}>{steps.map((step) => <option key={step} value={step}>步骤 {step}（第 {step + 1} 步）</option>)}</select></label>
        <label>查询锚点<select aria-label="自注意力锚点" value={descriptor.queryIndex} onChange={(event) => select((entry) => entry.layerId === descriptor.layerId && entry.step === descriptor.step && entry.queryIndex === Number(event.target.value), () => true)}>{anchors.map((entry) => <option key={entry.id} value={entry.queryIndex}>({entry.queryX}, {entry.queryY}) · 索引 {entry.queryIndex}</option>)}</select></label>
      </div>
      <p>查询坐标与索引从 0 开始：({descriptor.queryX}, {descriptor.queryY})，展平索引 {descriptor.queryIndex}。</p>
      {selectedMap ? <>
        <ResearchSpatialMap label={`自注意力锚点 (${selectedMap.queryX}, ${selectedMap.queryY}) 在 ${available.layers.find((layer) => layer.id === selectedMap.layerId)?.label} 步骤 ${selectedMap.step} 的实测概率图`} width={selectedMap.width} height={selectedMap.height} values={selectedMap.values} queryIndex={selectedMap.queryIndex} />
        <div className="h7-stat-list research-metrics"><RawMetric label="注意力熵 entropy" value={selectedMap.entropy} /><RawMetric label="峰值概率 peak" value={selectedMap.peak} /><RawMetric label="覆盖率 coverage" value={selectedMap.coverage} /></div>
        <JsonViewer value={selectedMap} filename={`${selectedMap.runId}-${selectedMap.id}.json`} highlight={false} />
      </> : <div className="unavailable-panel" role="status">{mapMessage}</div>}
    </> : <div className="unavailable-panel"><strong>Self-attention 未采集</strong><p role="status">{indexMessage}</p><p>请选择含自注意力产物的 H7 记录。只有 Cross-attention 的旧记录不能提供空间锚点图。</p></div>}
  </section>;
}
