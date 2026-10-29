import { useEffect, useRef, useState } from "react";
import type { RunComparison } from "../../../domain/research-experiments";
import { researchExperimentsApi } from "../../../providers/research-experiments-api";
import "./research-experiments.css";

const metricLabels = { mean: "均值", std: "标准差", l2: "L2 范数" };

export function CrossRunComparison({ runId, runs }: { runId: string | null; runs: Array<{ runId: string }> }) {
  const [other, setOther] = useState("");
  const [result, setResult] = useState<RunComparison | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const controller = useRef<AbortController | null>(null);
  useEffect(() => {
    controller.current?.abort(); setBusy(false); setResult(null); setError("");
    return () => controller.current?.abort();
  }, [runId, other]);
  const current = result?.provenance.left.runId === runId && result?.provenance.right.runId === other ? result : null;
  const compare = async () => {
    if (!runId || !other || busy) return;
    controller.current?.abort();
    const request = new AbortController(); controller.current = request;
    setBusy(true); setResult(null); setError("");
    try {
      const next = await researchExperimentsApi.compare(runId, other, request.signal);
      if (!request.signal.aborted) setResult(next);
    } catch (reason) {
      if (!request.signal.aborted) setError(reason instanceof Error ? reason.message : "比较失败");
    } finally { if (!request.signal.aborted) setBusy(false); }
  };
  return <section className="surface-card research-experiment-panel" aria-label="跨运行指标比较">
    <h2>跨运行潜变量比较</h2>
    <p>当前运行：{runId ?? "尚未选择"}。比较相同模型、引擎、采样设置及采集覆盖的实测均值、标准差和范数。</p>
    <div className="research-experiment-controls">
      <label>对照运行<select aria-label="对照运行" value={other} onChange={event => setOther(event.target.value)}>
        <option value="">选择另一条运行记录</option>
        {runs.filter(run => run.runId !== runId && run.runId !== "latest").map(run => <option key={run.runId} value={run.runId}>{run.runId}</option>)}
      </select></label>
      <button type="button" className="secondary-button" disabled={!runId || !other || other === runId || !runs.some(run => run.runId === other) || busy} onClick={() => void compare()}>{busy ? "核验与比较中…" : "比较实测指标"}</button>
    </div>
    {error && <p role="alert" className="inline-error">{error}</p>}
    {current && <>
      <p>已采集 {current.coverage.capturedCount} 个步号 · 配置 {current.coverage.configuredSteps} 步；采集索引：{current.coverage.capturedSteps.join("、")}。只比较已记录的采集点。</p>
      <p>{current.provenance.left.backend} · {current.provenance.left.samplingMethod} · {current.provenance.left.scheduler} · CFG {current.provenance.left.cfg}</p>
      <div className="research-table-scroll"><table aria-label="跨运行潜变量统计"><thead><tr><th>采集索引</th><th>指标</th><th>当前运行 A</th><th>对照运行 B</th><th>B − A</th></tr></thead>
        <tbody>{current.rows.map(row => <tr key={`${row.step}/${row.metric}`}><td>{row.step}</td><th scope="row">{metricLabels[row.metric]}</th><td>{row.left.toFixed(4)}</td><td>{row.right.toFixed(4)}</td><td>{row.delta.toFixed(4)}</td></tr>)}</tbody></table></div>
      <p>{current.limitations}</p>
      <div className="research-provenance">{(["left", "right"] as const).map(side => <div key={side}><strong>{side === "left" ? "A" : "B"} · {current.provenance[side].runId}</strong><p>模型：{current.provenance[side].modelId} · 来源：{current.provenance[side].source} / {current.provenance[side].metricSource}</p><code>{current.provenance[side].recordSha256}</code></div>)}</div>
    </>}
  </section>;
}
