import { useEffect, useRef, useState } from "react";
import type { FusionReplay } from "../../../domain/research-experiments";
import { researchExperimentsApi } from "../../../providers/research-experiments-api";
import "./research-experiments.css";

const modeLabels: Record<string, string> = { first_only: "仅首块", equal_mean: "等权均值", token_weighted: "有效 token 加权", anchor_residual: "锚点残差" };

export function MobileFusionExperiment() {
  const [open, setOpen] = useState(false);
  const [ready, setReady] = useState(false);
  const [json, setJson] = useState("");
  const [fileName, setFileName] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<FusionReplay | null>(null);
  const revision = useRef(0);
  const controller = useRef<AbortController | null>(null);
  useEffect(() => {
    const request = new AbortController();
    setBusy(false);
    if (open) {
      setReady(false); setError("");
      void researchExperimentsApi.capability(request.signal).then(() => { if (!request.signal.aborted) setReady(true); })
        .catch(reason => { if (!request.signal.aborted) setError(reason instanceof Error ? reason.message : "CPU 能力不可用"); });
    }
    return () => { request.abort(); controller.current?.abort(); revision.current++; };
  }, [open]);
  const load = async (file?: File) => {
    const token = ++revision.current;
    controller.current?.abort(); setBusy(false); setJson(""); setResult(null); setError(""); setFileName("");
    if (!file) return;
    try {
      if (file.size > 12 * 1024 * 1024) throw new Error("预测文件超过 12 MiB 上限");
      const value = await file.text();
      if (token !== revision.current) return;
      const parsed: unknown = JSON.parse(value);
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("需要预测 JSON 对象");
      setJson(value); setFileName(file.name);
    } catch (reason) { if (token === revision.current) setError(reason instanceof Error ? reason.message : "文件读取失败"); }
  };
  const replay = async () => {
    if (!ready || !json || busy) return;
    const request = new AbortController(); controller.current = request;
    setBusy(true); setResult(null); setError("");
    try {
      const value = await researchExperimentsApi.replay(json, request.signal);
      if (!request.signal.aborted) setResult(value);
    } catch (reason) { if (!request.signal.aborted) setError(reason instanceof Error ? reason.message : "融合重放失败"); }
    finally { if (!request.signal.aborted) setBusy(false); }
  };
  return <section className="surface-card research-experiment-panel" aria-label="手机算法数值实验">
    <button className="secondary-button" type="button" aria-expanded={open} onClick={() => setOpen(value => !value)}>手机 chunk 预测融合</button>
    {open && <>
      <h2>成对预测 CPU 重放</h2>
      <p>在同一个 latent 与时间步上，先计算每块正负条件的 CFG 预测，再比较四种融合。导入 mobile-chunk-predictions-v1 原始张量，最多 4 块、每块 65,536 个值。</p>
      <p>此面板仅重放导入张量；实际出图请使用“受控融合图像实验”。现有 H6 统计文件不能转换成原始预测，不会从提示词改写或统计量构造预测。</p>
      <label>导入成对预测 JSON<input type="file" accept=".json,application/json" aria-label="导入成对预测 JSON" onChange={event => void load(event.target.files?.[0])} /></label>
      {fileName && <p>已载入：{fileName}</p>}
      {error && <p role="alert" className="inline-error">{error}</p>}
      <button className="primary-button" type="button" disabled={!ready || !json || busy} onClick={() => void replay()}>{busy ? "CPU 重放中…" : "执行 CPU 融合重放"}</button>
      {result && <>
        <p>CPU 派生结果 · 导入来源未经设备验证；不代表手机速度、人物相似度或最终图像效果。</p>
        <p>{result.provenance.runId} · {result.provenance.modelId} · {result.provenance.engine} / {result.provenance.engineRevision} · 采集索引 {result.provenance.step} · {result.provenance.capturedAt}</p>
        <p>shape {result.shape.join(" × ")} · CFG {result.cfg} · α {result.alpha} · {result.chunkCount} 块</p>
        <div className="research-table-scroll"><table aria-label="预测融合数值对照"><thead><tr><th>模式</th><th>有效权重</th><th>平均绝对值</th><th>L2</th><th>相对等权 ΔL2</th><th>相对等权余弦</th></tr></thead>
          <tbody>{result.variants.map(variant => <tr key={variant.mode}><th scope="row">{modeLabels[variant.mode]}</th><td>{variant.weights.map(v => v.toFixed(4)).join(" / ")}</td><td>{variant.meanAbs.toFixed(4)}</td><td>{variant.l2.toFixed(4)}</td><td>{variant.deltaL2FromEqualMean.toFixed(4)}</td><td>{variant.cosineToEqualMean === null ? "未定义（零范数）" : variant.cosineToEqualMean.toFixed(4)}</td></tr>)}</tbody></table></div>
        <p>输入内容 SHA-256（内容摘要，不是设备认证）</p><code className="research-digest">{result.provenance.inputSha256}</code>
      </>}
    </>}
  </section>;
}
