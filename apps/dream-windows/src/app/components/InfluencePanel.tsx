import { useEffect, useState } from "react";
import type { RuntimeInfluence } from "../../domain/trace";
import { useDreamProvider } from "../providers";
import { JsonViewer } from "./JsonViewer";
import { RawMetric, ResearchSpatialMap, researchMessage } from "./ResearchArtifactView";

export function InfluencePanel({ runId, cfg }: { runId: string | null; cfg?: number }) {
  const provider = useDreamProvider();
  const [response, setResponse] = useState<RuntimeInfluence | null>(null);
  const [message, setMessage] = useState("正在读取 H6 条件影响记录…");
  const [stepId, setStepId] = useState<number | null>(null);
  const [chunkId, setChunkId] = useState<number | null>(null);
  useEffect(() => {
    let active = true;
    setResponse(null);
    setStepId(null);
    setChunkId(null);
    setMessage(runId ? "正在读取 H6 条件影响记录…" : "等待包含运行 ID 的原生记录…");
    if (runId) void provider.getInfluence(runId).then((value) => {
      if (!active) return;
      setResponse(value);
      if (!value.available) setMessage(researchMessage(value.message));
    }).catch(() => { if (active) setMessage("H6 条件影响读取失败，请刷新记录。"); });
    return () => { active = false; };
  }, [provider, runId]);
  const artifact = response?.available && response.runId === runId ? response : null;
  const visual = artifact?.method === "visual-reference-ablation-guided";
  const identity = visual || artifact?.method === "identity-ablation-guided";
  const step = artifact?.steps.find((entry) => entry.step === stepId) ?? artifact?.steps[0];
  const chunk = step?.chunks.find((entry) => entry.chunk === chunkId) ?? step?.chunks[0];
  return <div className="microscope-layout microscope-evidence-layout">
    <div className="microscope-main">
      <section className="surface-card influence-panel research-artifact-panel">
        <div className="section-title">H6 条件影响 <span className={`truth-label ${artifact ? "truth-observed" : "truth-unavailable"}`}>{artifact ? "条件影响 · 实测" : "张量不可用"}</span></div>
        {visual && <p className="research-banner">视觉参考干预：Plus Face 条件消融，不是 FaceID 生物身份分析。</p>}
        <p className="research-banner">H6 在采样步骤增加额外的研究前向计算和产物写入，耗时及内存开销高于基础生成。研究运行的总耗时不能直接当作生产性能；此记录未单独测量研究开销。</p>
        <p>{identity ? "身份条件干预：固定同一潜变量、时间步和提示词，额外关闭参考适配器注入做一次前向，将其 CFG 引导预测与完整人物条件预测比较。干预结果不参与采样，不是提示词分块融合。" : "在相同无条件张量和 CFG 下，将单个分块的引导预测与实际完整上下文引导预测比较（chunk-vs-full-guided）。这不代表 Windows 生产路径对分块预测取算术平均。"}</p>
        {artifact && step && chunk ? <>
          <p>运行：{artifact.runId} · 已采集 {artifact.capturedChunks} / {artifact.totalChunks} 个{identity ? "条件干预（关闭参考注入）" : "分块"}，{artifact.steps.length} 个步骤{!identity && ` · 每块 ${artifact.chunkSize} 个 Token 位置`}</p>
          <div className="h7-map-controls">
            <label>采样步骤<select aria-label="条件影响步骤" value={step.step} onChange={(event) => setStepId(Number(event.target.value))}>{artifact.steps.map((entry) => <option key={entry.step} value={entry.step}>步骤 {entry.step}（第 {entry.step + 1} 步）</option>)}</select></label>
            <label>空间图分块<select aria-label="条件影响分块" value={chunk.chunk} onChange={(event) => setChunkId(Number(event.target.value))}>{step.chunks.map((entry) => <option key={entry.chunk} value={entry.chunk}>分块 {entry.chunk} · Token {entry.tokenStart} → {entry.tokenEnd}</option>)}</select></label>
          </div>
          <div className="h7-stat-list research-metrics"><RawMetric label="CFG 差异 L2 · cfgDeltaL2" value={step.cfgDeltaL2} /><RawMetric label="CFG 余弦 · cfgCosine" value={step.cfgCosine} /></div>
          <div className="h7-matrix-scroll"><table className="h7-matrix research-metric-table" aria-label="分块原始指标"><thead><tr><th>分块</th><th>Token 起止</th><th>平均绝对值 meanAbs</th><th>范数 l2</th><th>对完整预测余弦 cosineFull</th><th>差异 deltaL2</th></tr></thead><tbody>{step.chunks.map((entry) => <tr key={entry.chunk} aria-selected={entry.chunk === chunk.chunk}><th>{entry.chunk}</th><td>{entry.tokenStart} → {entry.tokenEnd}</td><td>{String(entry.meanAbs)}</td><td>{String(entry.l2)}</td><td>{String(entry.cosineFull)}</td><td>{String(entry.deltaL2)}</td></tr>)}</tbody></table></div>
          <h3>通道平均绝对差异空间图</h3>
          <ResearchSpatialMap label={`H6 条件影响步骤 ${step.step} 分块 ${chunk.chunk} 的实测空间差异`} width={step.width} height={step.height} values={chunk.spatialDelta} zeroBaseline />
          <p className="muted-copy">表中数值与空间图均来自原始产物，不对未采集的步骤或分块插值；单个空间格的通道平均绝对差异与全张量 deltaL2 是不同指标。</p>
          <JsonViewer value={artifact} filename={`${artifact.runId}-conditioning-influence.json`} highlight={false} />
        </> : <div className="unavailable-panel"><strong>H6 条件影响张量不可用</strong><p role="status">{message}</p><p>请在生成页选择 H6（条件影响与潜空间）或 H7 研究采集后刷新记录。</p></div>}
      </section>
    </div>
    <aside className="surface-card measured-card research-artifact-panel"><div className="section-title">采集与解释边界</div>{identity ? <p>人物代表采集最多5步，扩展采集最多12步。此处比较移除参考适配器注入的干预预测，单个条件干预也可能有非零差异；它不是人脸相似度评分。</p> : <><p>最多 5 个采样步骤、3 个分块，每张空间图不超过 128 × 128。步骤、分块和 Token 位置均从 0 开始。</p><p>单分块时，与完整上下文的差异精确为 0。CFG=1 时无无条件分支，CFG 差异为 0{cfg === 1 ? "；本次 CFG=1。" : "。"}</p></>}<p>H6 是条件预测差异；H7 是空间位置或 Token 的注意力概率，两者含义不同。</p>{artifact && <p>来源：{artifact.source}<br />契约：{artifact.contractVersion}</p>}</aside>
  </div>;
}
