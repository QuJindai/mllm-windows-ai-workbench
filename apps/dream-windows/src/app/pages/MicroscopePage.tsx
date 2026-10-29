import { useEffect, useRef, useState } from "react";
import type { KeyboardEvent } from "react";
import { useDreamProvider } from "../providers";
import { isRuntimeTrace } from "../../domain/trace";
import { JsonViewer } from "../components/JsonViewer";
import { AttentionAnalysis } from "../components/AttentionAnalysis";
import { captureMessage, RecordedResearchPanel, useCaptureContext } from "./microscope-research";
import type { CaptureContext } from "./microscope-research";
import { CorrelationMatrix } from "../components/CorrelationMatrix";
import { LatentDeltaImage } from "../components/LatentDeltaImage";
import { SelectedChannelComparison } from "../components/SelectedChannelComparison";
import { CrossRunComparison } from "../components/research/CrossRunComparison";
import type { CurrentHardwareSnapshot, ResearchStatus, RuntimeAttentionIndex, RuntimeAttentionMap, RuntimeAttentionMapDescriptor, RuntimeCapabilities, RuntimeLatentTelemetry, RuntimeNode, RuntimeTrace, RuntimeTraceEvent, RuntimeTraceSummary } from "../../domain/trace";

type MicroscopeTab = "runtime" | "semantic" | "influence" | "latent" | "mechanism" | "expert" | "attention";

export function MicroscopePage() {
  const provider = useDreamProvider();
  const [tab, setTab] = useState<MicroscopeTab>("runtime");
  const [attentionKind, setAttentionKind] = useState<"cross" | "self">("cross");
  const [traceRuns, setTraceRuns] = useState<RuntimeTraceSummary[]>([]);
  const [selectedRunId, setSelectedRunId] = useState(() => new URLSearchParams(window.location.search).get("run") || "latest");
  const [refreshVersion, setRefreshVersion] = useState(0);
  const [trace, setTrace] = useState<RuntimeTrace | null>(null);
  const [traceMessage, setTraceMessage] = useState("等待 native 运行记录…");
  const [hardware, setHardware] = useState<CurrentHardwareSnapshot | null>(null);
  const [hardwareMessage, setHardwareMessage] = useState("正在读取当前硬件快照…");
  const [capabilities, setCapabilities] = useState<RuntimeCapabilities | null>(null);
  const [researchStatus, setResearchStatus] = useState<ResearchStatus | null>(null);
  const [attentionIndex, setAttentionIndex] = useState<RuntimeAttentionIndex | null>(null);
  const [attentionMessage, setAttentionMessage] = useState("正在读取 H7 注意力记录…");

  useEffect(() => {
    let active = true;
    void provider.listRuntimeTraces().then((value) => {
      if (active) setTraceRuns(value);
    }).catch(() => {
      if (active) setTraceRuns([]);
    });
    void provider.getHardware().then((value) => {
      if (!active) return;
      setHardware(value);
      setHardwareMessage("当前硬件快照已读取。");
    }).catch((reason: unknown) => {
      if (!active) return;
      setHardware(null);
      setHardwareMessage(reason instanceof Error ? reason.message : "当前硬件快照不可用");
    });
    void provider.getCapabilities().then((value) => {
      if (active) setCapabilities(value);
    }).catch(() => {
      if (active) setCapabilities(null);
    });
    void provider.getResearchStatus().then((value) => {
      if (active) setResearchStatus(value);
    }).catch(() => {
      if (active) setResearchStatus(null);
    });
    return () => {
      active = false;
    };
  }, [provider, refreshVersion]);

  useEffect(() => {
    let active = true;
    setTrace(null);
    setTraceMessage("正在读取 native 运行记录…");
    setAttentionIndex(null);
    setAttentionMessage("等待当前运行记录…");
    void provider.getRuntimeTrace(selectedRunId).then((value) => {
      if (!active) return;
      if (isRuntimeTrace(value)) {
        setTrace(value);
        setTraceMessage(value.truth === "demo"
          ? "数据来自测试提供方固定样例。"
          : selectedRunId === "latest"
            ? "数据来自最近一次 native 运行记录。"
            : `数据来自运行记录 ${value.runId}。`);
      } else {
        setTrace(null);
        setTraceMessage(localizeResearchMessage(value.message));
      }
    }).catch((reason: unknown) => {
      if (!active) return;
      setTrace(null);
      setTraceMessage(reason instanceof Error ? reason.message : "运行记录不可用");
    });
    return () => { active = false; };
  }, [provider, selectedRunId, refreshVersion]);

  useEffect(() => {
    const runId = trace?.runId;
    if (!runId) {
      setAttentionIndex(null);
      setAttentionMessage("等待包含运行 ID 的 native 记录…");
      return;
    }
    const needsAttention = tab === "semantic" || tab === "expert" || (tab === "attention" && attentionKind === "cross");
    if (!needsAttention || attentionIndex?.runId === runId) return;
    let active = true;
    setAttentionMessage("正在读取 H7 注意力记录…");
    void provider.getAttentionIndex(runId).then((value) => {
      if (!active) return;
      setAttentionIndex(value);
      setAttentionMessage(value.available ? "已读取实测 H7 注意力索引。" : localizeResearchMessage(value.message));
    }).catch((reason: unknown) => {
      if (!active) return;
      const message = `H7 注意力索引读取失败。${localizeResearchMessage(reason instanceof Error ? reason.message : "H7 注意力记录不可用")}`;
      setAttentionIndex({ available: false, runId, message, truth: "unavailable" });
      setAttentionMessage(message);
    });
    return () => { active = false; };
  }, [attentionIndex?.runId, provider, tab, trace?.runId, attentionKind]);

  const tabs: Array<{ id: MicroscopeTab; label: string }> = [
    { id: "runtime", label: "运行时" },
    { id: "semantic", label: "语义" },
    { id: "influence", label: "条件影响" },
    { id: "latent", label: "潜空间" },
    { id: "mechanism", label: "机制" },
    { id: "expert", label: "专家" },
    { id: "attention", label: "H7 注意力" },
  ];
  const tabRefs = useRef<Partial<Record<MicroscopeTab, HTMLButtonElement | null>>>({});
  const needsSelfAttention = tab === "attention" && attentionKind === "self";
  const needsInfluence = tab === "influence";
  const needsAttention = (tab === "attention" && attentionKind === "cross") || tab === "semantic";
  const needsLatent = tab === "latent" || tab === "mechanism";
  const researchRunId = selectedRunId === "latest" ? trace?.runId ?? null : selectedRunId;
  const currentSummary = traceRuns.find((run) => run.runId === researchRunId);
  const currentTrace = trace?.runId === researchRunId ? trace : null;
  const currentAttentionIndex = attentionIndex?.runId === researchRunId ? attentionIndex : null;
  const needsCaptureContext = tab === "attention" || tab === "influence" || tab === "semantic" || tab === "expert";
  const captureContext = useCaptureContext(needsCaptureContext && researchRunId !== "latest" ? researchRunId : null, currentTrace?.evidence?.modelId ?? currentSummary?.modelId, refreshVersion);
  const attentionLoading = currentTrace !== null && !currentAttentionIndex;
  const attentionGuidance = captureMessage(captureContext, "H7", attentionMessage, attentionLoading);
  const compatibleRun = traceRuns.find((run) => needsSelfAttention ? run.hasSelfAttention === true : needsInfluence ? run.hasInfluence === true : needsAttention ? run.hasAttention : needsLatent ? run.hasLatent : false);
  const missingCompatibleData = needsSelfAttention ? !currentSummary?.hasSelfAttention : needsInfluence ? !currentSummary?.hasInfluence : needsAttention ? !currentSummary?.hasAttention && !attentionIndex?.available : needsLatent ? !currentSummary?.hasLatent && !trace?.latentTelemetry?.length : false;
  const compatibleLabel = needsSelfAttention ? "H7自注意力" : needsInfluence ? "H6条件影响" : needsAttention ? "H7" : "潜空间";
  const handleTabKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    let nextIndex: number | null = null;
    if (event.key === "ArrowRight") nextIndex = (index + 1) % tabs.length;
    if (event.key === "ArrowLeft") nextIndex = (index - 1 + tabs.length) % tabs.length;
    if (event.key === "Home") nextIndex = 0;
    if (event.key === "End") nextIndex = tabs.length - 1;
    if (nextIndex === null) return;
    event.preventDefault();
    const nextTab = tabs[nextIndex].id;
    setTab(nextTab);
    tabRefs.current[nextTab]?.focus();
  };

  return (
    <section className="microscope-page">
      <div className="surface-card microscope-run-bar">
        <label>运行记录<select value={selectedRunId} aria-label="选择运行记录" onChange={(event) => setSelectedRunId(event.target.value)}>
          <option value="latest">最近一次本地生成</option>
          {traceRuns.map((run) => <option key={run.runId} value={run.runId}>{[run.hasInfluence && "H6条件影响", run.hasSelfAttention && "H7自注意力", run.hasAttention && "H7交叉注意力", run.hasLatent && "潜空间"].filter(Boolean).join(" / ") || "基础"} · {run.runId} · {run.modelId ?? "未知模型"}</option>)}
        </select></label>
        <button type="button" className="secondary-button" onClick={() => setRefreshVersion((value) => value + 1)}>刷新记录</button>
        {missingCompatibleData && compatibleRun && <button type="button" className="secondary-button" onClick={() => setSelectedRunId(compatibleRun.runId)}>选择最近的{compatibleLabel}记录</button>}
        {missingCompatibleData && <p>{compatibleRun ? "当前记录缺少此视图的数据，可选择上方的兼容记录。" : "暂无兼容记录。当前任务的采集情况见下方；可在生成完成后刷新记录。"}</p>}
      </div>
      {needsCaptureContext && captureContext.publicationFailed && <p role="status">运行记录发布失败：本次任务的研究产物未完整发布，已生成图片仍保留。各视图的采集状态按本次请求的级别判断。</p>}
      <div className="microscope-tabs" role="tablist" aria-label="显微镜视图">
        {tabs.map((entry, index) => (
          <button
            key={entry.id}
            ref={(element) => { tabRefs.current[entry.id] = element; }}
            id={`microscope-tab-${entry.id}`}
            className={tab === entry.id ? "is-active" : ""}
            type="button"
            role="tab"
            aria-controls={`microscope-panel-${entry.id}`}
            aria-selected={tab === entry.id}
            tabIndex={tab === entry.id ? 0 : -1}
            onClick={() => setTab(entry.id)}
            onKeyDown={(event) => handleTabKeyDown(event, index)}
          >
            {entry.label}
          </button>
        ))}
      </div>
      <div id={`microscope-panel-${tab}`} role="tabpanel" aria-labelledby={`microscope-tab-${tab}`}>
        {tab === "runtime" && <RuntimePanel trace={trace} traceMessage={traceMessage} hardware={hardware} hardwareMessage={hardwareMessage} />}
        {tab === "semantic" && <SemanticPanel trace={currentTrace} attentionIndex={currentAttentionIndex} attentionMessage={`${attentionGuidance} ${attentionMessage}`} />}
        {tab === "influence" && <RecordedResearchPanel key={`${selectedRunId}/${refreshVersion}`} kind="influence" runId={researchRunId} context={captureContext} cfg={currentTrace?.evidence?.cfg} />}
        {tab === "latent" && <><LatentPanel trace={trace} /><CrossRunComparison key={`${selectedRunId}/${refreshVersion}`} runId={researchRunId} runs={traceRuns} /></>}
        {tab === "mechanism" && <MechanismPanel trace={trace} />}
        {tab === "expert" && <ExpertPanel trace={currentTrace} traceMessage={traceMessage} attentionIndex={currentAttentionIndex} attentionMessage={attentionMessage} />}
        {tab === "expert" && !currentAttentionIndex?.available && <p role="status">{attentionGuidance}</p>}
        {tab === "attention" && <>
          <div className="notebook-tabs" role="tablist" aria-label="注意力类型">
            <button type="button" role="tab" id="attention-kind-cross" aria-controls="attention-kind-panel-cross" aria-selected={attentionKind === "cross"} className={attentionKind === "cross" ? "is-active" : ""} onClick={() => setAttentionKind("cross")}>Cross-attention 交叉注意力</button>
            <button type="button" role="tab" id="attention-kind-self" aria-controls="attention-kind-panel-self" aria-selected={attentionKind === "self"} className={attentionKind === "self" ? "is-active" : ""} onClick={() => setAttentionKind("self")}>Self-attention 自注意力</button>
          </div>
          <div role="tabpanel" id={`attention-kind-panel-${attentionKind}`} aria-labelledby={`attention-kind-${attentionKind}`}>
            {attentionKind === "self"
              ? <RecordedResearchPanel key={`${selectedRunId}/${refreshVersion}`} kind="self" runId={researchRunId} context={captureContext} />
              : <AttentionPanel key={`${researchRunId}/${refreshVersion}`} runId={researchRunId ?? "latest"} capability={capabilities?.attention ?? null} researchStatus={researchStatus} index={currentAttentionIndex} indexMessage={attentionMessage} captureContext={captureContext} indexLoading={attentionLoading} />}
          </div>
        </>}
      </div>
    </section>
  );
}

function SemanticPanel({ trace, attentionIndex, attentionMessage }: { trace: RuntimeTrace | null; attentionIndex: RuntimeAttentionIndex | null; attentionMessage: string }) {
  const model = trace?.evidence?.modelId ?? "—";
  const steps = trace?.evidence?.steps ?? "—";
  const cfg = trace?.evidence?.cfg ?? "—";
  const conditioningObserved = trace?.events?.some((event) => event.phase === "conditioning" && event.truth === "observed");
  const availableAttention = attentionIndex?.available ? attentionIndex : null;
  const chunks = availableAttention
    ? [...new Set(availableAttention.tokens.map((token) => token.chunk))]
      .sort((left, right) => left - right)
      .map((chunk) => ({ chunk, tokens: availableAttention.tokens.filter((token) => token.chunk === chunk) }))
    : [];
  return (
    <div className="microscope-layout microscope-evidence-layout">
      <div className="microscope-main">
        <div className="surface-card semantic-panel">
          <div className="section-title">提示词与分块 <span className="truth-label truth-derived">Prompt / Chunk / CFG · 派生结构</span></div>
          <h2>从提示词到条件嵌入的可追踪入口。</h2>
          <div className="semantic-flow"><div><strong>提示词</strong><span>原始输入</span></div><b>→</b><div><strong>分词 / 分块</strong><span>token ids</span></div><b>→</b><div><strong>条件编码</strong><span>CLIP text</span></div><b>→</b><div><strong>CFG 引导链路</strong><span>positive / negative</span></div></div>
          {trace ? <div className="evidence-table"><span>模型</span><strong>{model}</strong><span>步数</span><strong>{steps}</strong><span>CFG</span><strong>{cfg}</strong><span>条件编码阶段</span><strong>{conditioningObserved ? "已观测" : "未导出"}</strong></div> : <div className="unavailable-panel"><strong>等待 native 运行记录</strong><p>只有产生真实运行记录后，才展示输入身份和条件编码阶段。</p></div>}
        </div>
        <div className="surface-card token-chunk-panel">
          <div className="section-title">Token / Chunk 原始记录 <span className={`truth-label ${availableAttention ? "truth-observed" : "truth-unavailable"}`}>{availableAttention ? "H7 tokenizer · 实测" : "不可用"}</span></div>
          {availableAttention ? <div className="semantic-evidence-stack">
            <ul className="semantic-token-list" aria-label="实测 Token 列表">
              {availableAttention.tokens.map((token) => <li key={token.slot}><span>{String(token.slot).padStart(4, "0")}</span><strong>{token.text}</strong><small>ID {token.tokenId}</small><small>权重 {token.weight.toFixed(2)}</small></li>)}
            </ul>
            <div className="semantic-chunk-list" role="group" aria-label="实测 Chunk 列表">
              {chunks.map(({ chunk, tokens }) => <article key={chunk}><strong>Chunk {chunk + 1}</strong><span>{tokens.map((token) => token.text).join(" ")}</span><small>{tokens.length} 个 token</small></article>)}
            </div>
          </div> : <div className="unavailable-grid">
            <div className="unavailable-panel"><strong>原始 token 不可用</strong><p>{attentionMessage || "当前 trace 没有导出 native tokenizer 的 token ID 或权重。"}</p></div>
            <div className="unavailable-panel"><strong>原始 chunk 不可用</strong><p>当前 trace 没有导出经过验证的 native 分块边界或逐块文本。</p></div>
          </div>}
        </div>
      </div>
      <aside className="surface-card measured-card"><div className="section-title">证据等级</div><p>模型身份、步数、CFG 和阶段事件只采用运行记录中的实测值。</p><p>{availableAttention ? `Token ID、权重和 Chunk 来自 ${availableAttention.source} 的 ${availableAttention.contractVersion} 记录。` : "不会通过重新分词或拆分字符串来伪造 token、chunk 或 embedding 数值。"}</p></aside>
    </div>
  );
}

function MechanismPanel({ trace }: { trace: RuntimeTrace | null }) {
  const telemetry = (trace?.latentTelemetry ?? []).filter((sample) => sample.truth === "observed");
  const events = (trace?.events ?? []).filter((event) => event.truth === "observed");
  return <div className="microscope-layout microscope-evidence-layout"><div className="microscope-main"><div className="surface-card mechanism-panel"><div className="section-title">可验证的计算关系 <span className="truth-label truth-derived">实测优先 · 派生次之</span></div><div className="mechanism-grid"><article><h3>Δz</h3><p>当前 latent − 上一步 latent</p><strong>{telemetry.length ? "已观测" : "未导出"}</strong></article><article><h3>L2 / 平均 |Δz|</h3><p>由真实 latent tensor 逐步计算</p><strong>{telemetry.length ? "可计算" : "未导出"}</strong></article><article><h3>余弦相似度</h3><p>衡量相邻 latent 的方向一致性</p><strong>{telemetry.length ? "可计算" : "未导出"}</strong></article><article><h3>阶段时间</h3><p>来自本次引擎的阶段记录，不用比例估算</p><strong>{events.length ? "已观测" : "未导出"}</strong></article></div><div className="evidence-rule"><strong>观察值优先</strong><span>引擎元数据 / 阶段记录 → 直接测量；由它们计算的指标 → 派生；缺少输入 → 不可用。</span></div></div></div><aside className="surface-card measured-card"><div className="section-title">解读提示</div><p>显微镜不会把总耗时按经验拆成 UNet、VAE 或 attention，也不会把 RGB 投影当作四通道 latent。</p><p>当前记录：{trace ? "已接收" : "等待中"}。</p></aside></div>;
}

function ExpertPanel({ trace, traceMessage, attentionIndex, attentionMessage }: { trace: RuntimeTrace | null; traceMessage: string; attentionIndex: RuntimeAttentionIndex | null; attentionMessage: string }) {
  const badge = !trace
    ? { className: "truth-unavailable", text: "当前 trace · 不可用" }
    : trace.truth === "demo"
      ? { className: "truth-demo", text: "固定样例 · 演示" }
      : trace.truth === "derived"
        ? { className: "truth-derived", text: "当前 trace · 派生" }
        : { className: "truth-observed", text: "当前 trace · 实测" };
  const availableAttention = attentionIndex?.available ? attentionIndex : null;
  return <div className="microscope-layout microscope-evidence-layout"><div className="microscope-main"><div className="surface-card expert-panel"><div className="section-title">原始运行记录 <span className={`truth-label ${badge.className}`}>{badge.text}</span></div><p className="expert-warning">不会把推测当作实测。以下内容是后端公开边界过滤后的当前 trace 响应。</p>{trace ? <JsonViewer value={trace} filename={`${trace.runId}-trace.json`} /> : <div className="unavailable-panel"><strong>原始记录不可用</strong><p>{traceMessage}</p></div>}</div><div className="surface-card expert-panel"><div className="section-title">H7 attention 索引 <span className={`truth-label ${availableAttention ? "truth-observed" : "truth-unavailable"}`}>{availableAttention ? "实测" : "不可用"}</span></div>{availableAttention ? <JsonViewer value={availableAttention} filename={`${availableAttention.runId}-attention.json`} /> : <div className="unavailable-panel"><strong>H7 attention 索引不可用</strong><p>{attentionMessage}</p></div>}</div></div><aside className="surface-card measured-card"><div className="section-title">诊断清单</div><ul><li>运行 ID：{trace?.runId ?? "—"}</li><li>观测节点：{trace?.nodes.filter((node) => node.truth === "observed").length ?? "—"}</li><li>观测阶段事件：{trace?.events?.filter((event) => event.truth === "observed").length ?? "—"}</li><li>Latent 遥测：{trace?.latentTelemetry?.length ? "已导出" : "未导出"}</li><li>{availableAttention ? `H7 attention 张量：${availableAttention.maps.length} 张实测图` : "H7 attention 张量：未导出"}</li></ul></aside></div>;
}

function RuntimePanel({ trace, traceMessage, hardware, hardwareMessage }: {
  trace: RuntimeTrace | null;
  traceMessage: string;
  hardware: CurrentHardwareSnapshot | null;
  hardwareMessage: string;
}) {
  const nodes = (trace?.nodes ?? []).filter((node) => node.truth === "observed");
  const events = (trace?.events ?? []).filter((event) => event.truth === "observed");
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const selectedNode = nodes.find((node) => node.id === selectedNodeId) ?? nodes[0] ?? null;
  const displayNodes: RuntimeNode[] = nodes.length
    ? nodes
    : [{ id: "waiting", name: "等待 native 记录", backend: "不可用", status: "skipped", truth: "unavailable" }];
  const unetEvent = events.find((event) => event.phase === "unet_sampling");
  const vaeEvent = events.find((event) => event.phase === "vae_decode");
  const traceBadge = !trace
    ? { className: "truth-unavailable", text: "等待中" }
    : trace.truth === "demo"
      ? { className: "truth-demo", text: "固定样例 · 演示" }
      : trace.truth === "derived"
        ? { className: "truth-derived", text: "已采集 · 派生" }
        : { className: "truth-observed", text: "已采集 · 实测" };

  return (
    <div className="microscope-layout">
      <div className="microscope-main">
        <div className="surface-card run-selector">
          <span>{trace?.runId ?? "等待读取记录"}</span>
          <span className={`live-pill ${trace ? "is-live" : ""} ${traceBadge.className}`}>● {traceBadge.text}</span>
        </div>

        <CurrentHardwareEvidence hardware={hardware} message={hardwareMessage} />

        <div className="surface-card time-accounting">
          <div className="section-title">时间统计 <small>（本次运行）</small></div>
          <div className="time-grid">
            <Metric label="总耗时" value={trace ? formatSeconds(trace.totalTimeMs) : "—"} />
            <Metric label="UNet 采样" value={unetEvent ? formatDuration(unetEvent.durationMs) : "—"} />
            <Metric label="VAE 解码" value={vaeEvent ? formatDuration(vaeEvent.durationMs) : "—"} />
            <Metric label="已采集阶段" value={events.length ? String(events.length) : "—"} />
          </div>
        </div>

        <div className="surface-card runtime-graph">
          <div className="section-title">
            运行时计算图
            <span className="graph-legend">● 已执行　● 跳过　● 运行中　● 错误</span>
          </div>
          <p className="trace-source">{nodes.length ? "点击节点查看实测耗时和原生证据。" : traceMessage}</p>
          <div className="node-flow">
            {displayNodes.map((node, index) => (
              <button
                className={"runtime-node " + (selectedNode?.id === node.id && node.id !== "waiting" ? "is-selected" : "")}
                key={node.id}
                type="button"
                disabled={node.id === "waiting"}
                aria-label={"检查 " + node.name}
                aria-pressed={selectedNode?.id === node.id}
                onClick={() => setSelectedNodeId(node.id)}
              >
                <span className={"node-status " + node.status} aria-hidden="true" />
                <strong>{index + 1}. {node.name}</strong>
                <small>{node.backend}</small>
                <span>{node.durationMs !== undefined ? formatDuration(node.durationMs) : "—"}</span>
              </button>
            ))}
          </div>
        </div>

        <MeasuredTimeline events={events} totalTimeMs={trace?.totalTimeMs ?? 0} onSelect={setSelectedNodeId} />
      </div>

      <RuntimeInspector trace={trace} node={selectedNode} traceMessage={traceMessage} />
    </div>
  );
}

function MeasuredTimeline({ events, totalTimeMs, onSelect }: {
  events: RuntimeTraceEvent[];
  totalTimeMs: number;
  onSelect: (nodeId: string) => void;
}) {
  return (
    <div className="surface-card trace-timeline">
      <div className="section-title">
        原生阶段时间线
        <small>{events.length ? "本次引擎实测阶段记录" : "本次记录没有阶段日志"}</small>
      </div>
      {events.length ? (
        <div className="trace-event-list">
          {events.map((event) => (
            <div className="trace-event-row" key={event.phase}>
              <div className="trace-event-heading">
                <button type="button" onClick={() => onSelect(event.phase)}>{phaseLabel(event.label)}</button>
                <strong>{formatDuration(event.durationMs)}</strong>
              </div>
              <div className="trace-event-track" aria-hidden="true">
                <span className="trace-event-bar" style={{ width: eventWidth(event.durationMs, totalTimeMs) }} />
              </div>
              <span className="trace-event-truth">已观测</span>
            </div>
          ))}
        </div>
      ) : (
        <div className="unavailable-panel">
          <strong>原生阶段耗时不可用</strong>
          <p>本次运行只有原生总耗时元数据，不显示估算的阶段拆分。</p>
        </div>
      )}
    </div>
  );
}

function RuntimeInspector({ trace, node, traceMessage }: {
  trace: RuntimeTrace | null;
  node: RuntimeNode | null;
  traceMessage: string;
}) {
  const evidence = trace?.evidence;
  return (
    <aside className="surface-card runtime-inspector">
      <div className="section-title">运行时检查器 <span className="collapse-mark">⌃</span></div>
      <h2>{node ? phaseLabel(node.name) : "未选择运行记录"}</h2>
      <div className="inspector-block">
        <span>状态</span>
        <strong>{node ? statusLabel(node.status) : "不可用"}{node ? " · " + truthLabel(node.truth) : ""}</strong>
      </div>
      <div className="inspector-block">
        <span>节点详情</span>
        {node ? (
          <div className="inspector-grid">
            <span>后端</span><strong>{node.backend}</strong>
            <span>耗时</span><strong>{node.durationMs !== undefined ? formatDuration(node.durationMs) : "—"}</strong>
            <span>形状</span><strong>{node.shape ?? "—"}</strong>
            {node.expectedCalls !== undefined && <><span>预期调用 · 派生</span><strong>{node.expectedCalls}</strong></>}
            {node.observedCalls !== undefined && <><span>实际调用 · 实测</span><strong>{node.observedCalls}</strong></>}
          </div>
        ) : (
          <p>{traceMessage}</p>
        )}
      </div>
      <div className="inspector-block">
        <span>证据</span>
        <p>{trace
          ? (trace.events?.length ? "数据来自本次引擎的实测阶段记录。" : "数据来自原生生成元数据；阶段耗时日志不可用。")
          : traceMessage}</p>
        {trace && <div className="inspector-grid">
          <span>模型</span><strong>{evidence?.modelId ?? "—"}</strong>
          <span>采样器</span><strong>{evidence?.samplingMethod ?? "—"}</strong>
          <span>调度器</span><strong>{evidence?.scheduler ?? "—"}</strong>
          <span>步数 / CFG</span><strong>{evidence?.steps ?? "—"} / {evidence?.cfg ?? "—"}</strong>
          {evidence?.backend && <><span>本次运行后端{evidence.backendTruth === "observed" ? " · 实测" : ""}</span><strong>{evidence.backend}</strong></>}
          <span>本次运行峰值 VRAM</span><strong>{formatMiB(evidence?.peakVramMiB)}</strong>
          <span>本次运行峰值 RAM</span><strong>{formatBytes(evidence?.peakRamBytes)}</strong>
        </div>}
        {evidence?.wrapperLogPath && <code className="evidence-path">{evidence.wrapperLogPath}</code>}
      </div>
    </aside>
  );
}

function CurrentHardwareEvidence({ hardware, message }: { hardware: CurrentHardwareSnapshot | null; message: string }) {
  const observed = hardware?.truth === "observed" && !hardware.isMock;
  const currentTruth = observed
    ? { className: "truth-observed", text: "当前 · 实测" }
    : hardware ? { className: "truth-demo", text: "当前 · 演示" } : { className: "truth-unavailable", text: "不可用" };
  const unavailableTruth = { className: "truth-unavailable", text: "不可用" };
  const backendTruth = hardware?.backend && hardware.backendTruth === "derived" && !hardware.isMock
    ? { className: "truth-derived", text: "检测 · 派生" }
    : hardware?.isMock ? { className: "truth-demo", text: "检测 · 演示" } : unavailableTruth;
  const readings = [
    { label: "当前 VRAM", value: hardware ? `${formatMiBNumber(hardware.vramUsedMiB)} / ${formatMiBNumber(hardware.vramTotalMiB)} MiB` : "—", truth: currentTruth },
    { label: "当前 RAM", value: hardware ? formatBytePair(hardware.ramUsedBytes, hardware.ramTotalBytes) : "—", truth: currentTruth },
    { label: "当前 GPU 温度", value: hardware?.gpuTempC == null ? "—" : `${hardware.gpuTempC} °C`, truth: hardware?.gpuTempC == null ? unavailableTruth : currentTruth },
    { label: "检测后端", value: hardware?.backend ?? "—", truth: backendTruth },
  ];
  return (
    <div className="surface-card current-hardware-evidence">
      <div className="section-title">当前硬件快照 <small>{hardware ? "页面载入时调用 getHardware" : message}</small></div>
      <div className="current-hardware-grid">
        {readings.map((reading) => <article className="current-hardware-card" key={reading.label}><div><span>{reading.label}</span><span className={`truth-label ${reading.truth.className}`}>{reading.truth.text}</span></div><strong>{reading.value}</strong></article>)}
      </div>
    </div>
  );
}

function LatentPanel({ trace }: { trace: RuntimeTrace | null }) {
  const events = (trace?.events ?? []).filter((event) => event.truth === "observed");
  const unetEvent = events.find((event) => event.phase === "unet_sampling");
  const vaeEvent = events.find((event) => event.phase === "vae_decode");
  const frames = trace?.latentPreviewFrames ?? [];
  const telemetry = (trace?.latentTelemetry ?? []).filter((sample) => sample.truth === "observed");
  const [frameIndex, setFrameIndex] = useState(0);
  const [telemetryIndex, setTelemetryIndex] = useState(0);
  useEffect(() => {
    setFrameIndex(0);
    setTelemetryIndex(0);
  }, [trace?.runId]);
  const boundedFrameIndex = Math.min(frameIndex, Math.max(0, frames.length - 1));
  const boundedTelemetryIndex = Math.min(telemetryIndex, Math.max(0, telemetry.length - 1));
  const selectedFrame = frames[boundedFrameIndex];

  return (
    <div className="latent-layout">
      <div className="surface-card latent-hero">
        <div className="section-title">过程动态 <span className={"truth-label " + (telemetry.length ? "truth-observed" : "truth-unavailable")}>{telemetry.length ? "当前 trace · 实测" : "指标不可用"}</span></div>
        <h2>观察去噪过程中每一步 Latent（潜变量）的真实变化。</h2>
        {trace ? (
          <>
            <div className="process-summary-grid">
              <Metric label="原生总耗时" value={formatSeconds(trace.totalTimeMs)} />
              <Metric label="UNet 采样" value={unetEvent ? formatDuration(unetEvent.durationMs) : "—"} />
              <Metric label="VAE 解码" value={vaeEvent ? formatDuration(vaeEvent.durationMs) : "—"} />
              <Metric label="阶段事件" value={events.length ? String(events.length) : "—"} />
            </div>
            {telemetry.length > 0 && <LatentTelemetryInspector telemetry={telemetry} selectedIndex={boundedTelemetryIndex} onSelect={setTelemetryIndex} />}
            <div className="phase-list">
              <div className="section-title">已观测阶段</div>
              {events.length ? events.map((event) => (
                <div className="phase-list-row" key={event.phase}><span>{phaseLabel(event.label)}</span><strong>{formatDuration(event.durationMs)}</strong></div>
              )) : <p>本次运行没有阶段事件。</p>}
            </div>
            {frames.length > 0 && <div className="latent-preview-card">
              <div className="section-title">Latent 投影预览 <small>stable-diffusion.cpp RGB preview 回调（辅助视图）</small></div>
              {selectedFrame?.imageUrl ? <img className="latent-preview-image" src={selectedFrame.imageUrl} alt={`Latent 投影第 ${selectedFrame.step + 1} 步`} loading="lazy" decoding="async" /> : <div className="latent-preview-missing">投影帧 URL 不可用</div>}
              <div className="latent-step-controls">
                <button type="button" className="secondary-button" aria-label="上一个 latent 步骤" disabled={boundedFrameIndex <= 0} onClick={() => setFrameIndex((current) => Math.max(0, current - 1))}>←</button>
                <input type="range" aria-label="Latent 预览步骤" min="0" max={Math.max(0, frames.length - 1)} value={boundedFrameIndex} onChange={(event) => setFrameIndex(Number(event.target.value))} />
                <button type="button" className="secondary-button" aria-label="下一个 latent 步骤" disabled={boundedFrameIndex >= frames.length - 1} onClick={() => setFrameIndex((current) => Math.min(frames.length - 1, current + 1))}>→</button>
                <strong>第 {selectedFrame ? selectedFrame.step + 1 : 0} / {frames.length} 步</strong>
              </div>
              <div className="latent-frame-strip">
                {frames.map((frame, index) => <button type="button" className={index === boundedFrameIndex ? "is-selected" : ""} aria-label={`选择 latent 第 ${index + 1} 步`} aria-pressed={index === boundedFrameIndex} key={frame.fileName} onClick={() => setFrameIndex(index)}>{frame.imageUrl ? <img src={frame.imageUrl} alt="" loading="lazy" decoding="async" /> : <span>{index + 1}</span>}</button>)}
              </div>
            </div>}
            {telemetry.length === 0 && <div className="unavailable-panel">
              <strong>原始 latent 通道不可用</strong>
              <p>若上方存在逐步帧，它们只是 native latent 的 RGB 投影；当前 Basic 记录没有采集投影或四通道 tensor，因此 L2、余弦相似度、直方图和通道图不会伪造。</p>
            </div>}
          </>
        ) : (
          <div className="latent-empty">等待原生 Latent 记录…</div>
        )}
      </div>
      <aside className="surface-card measured-card">
        <div className="section-title">这里测量什么 <span className="collapse-mark">⌃</span></div>
        <h3>直接测量</h3>
        <p>只显示引擎元数据、阶段记录和真实回调输出的数值。</p>
        <ul><li>原生总生成耗时</li><li>条件编码耗时</li><li>UNet 采样耗时</li><li>VAE 解码耗时</li><li>每步 Latent 投影</li>{telemetry.length > 0 && <><li>每步 Latent Δz 指标</li><li>四通道统计与直方图</li></>}</ul>
        <h3>独立研究采集</h3>
        <p>H7 注意力页读取独立研究产物；是否采集成功以所选记录的有效 Self/Cross 张量为准。</p>
      </aside>
    </div>
  );
}

function LatentTelemetryInspector({ telemetry, selectedIndex, onSelect }: { telemetry: RuntimeLatentTelemetry[]; selectedIndex: number; onSelect: (index: number) => void }) {
  const boundedIndex = Math.min(Math.max(0, selectedIndex), telemetry.length - 1);
  const sample = telemetry[boundedIndex] ?? telemetry[0];
  if (!sample) return null;
  const previous = telemetry[boundedIndex - 1];
  const final = telemetry[telemetry.length - 1];
  const channels = sample.channels.filter((channel) => channel.truth === "observed").sort((left, right) => left.channel - right.channel);
  const hasFourChannels = channels.length === 4 && channels.every((channel, index) => channel.channel === index);

  return (
    <div className="latent-inspector-stack" aria-label="过程动态与 Latent 状态">
      <div className="section-title">Latent 状态检查器 <small>真实四通道张量 · 形状 {sample.shape.join(" × ")}</small></div>
      <div className="telemetry-step-controls">
        <button type="button" className="secondary-button" aria-label="上一个遥测步骤" disabled={boundedIndex === 0} onClick={() => onSelect(Math.max(0, boundedIndex - 1))}>←</button>
        <input type="range" aria-label="Latent 遥测步骤" min="0" max={Math.max(0, telemetry.length - 1)} value={boundedIndex} onChange={(event) => onSelect(Math.min(telemetry.length - 1, Math.max(0, Number(event.target.value))))} />
        <button type="button" className="secondary-button" aria-label="下一个遥测步骤" disabled={boundedIndex === telemetry.length - 1} onClick={() => onSelect(Math.min(telemetry.length - 1, boundedIndex + 1))}>→</button>
        <strong>记录 {boundedIndex + 1} / {telemetry.length} · 第 {sample.step + 1} 步</strong>
      </div>
      <div className="latent-dynamics-grid">
        <Metric label="Δz L2" value={formatLatentMetric(sample.deltaL2)} />
        <Metric label="平均 |Δz|" value={formatLatentMetric(sample.deltaMeanAbs)} />
        <Metric label="余弦相似度" value={formatLatentMetric(sample.cosine)} />
        <Metric label="Latent 均值" value={formatLatentMetric(sample.mean)} />
        <Metric label="Latent 标准差" value={formatLatentMetric(sample.std)} />
      </div>

      {hasFourChannels ? <>
        <div className="latent-channel-section">
          <div className="section-title">Latent 四通道 <span className="truth-label truth-observed">当前步骤 · 实测</span></div>
          <div className="latent-channel-grid">
            {channels.map((channel) => (
              <div className="latent-channel-card" key={channel.channel}>
                <strong>通道 C{channel.channel}</strong>
                {channel.imageUrl ? <img src={channel.imageUrl} alt={`通道 C${channel.channel}`} loading="lazy" decoding="async" /> : <div className="latent-preview-missing">通道图不可用</div>}
                <span>均值 {formatLatentMetric(channel.mean)}　标准差 {formatLatentMetric(channel.std)}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="latent-analysis-grid">
          <div className="latent-table-wrap">
            <div className="section-title">通道统计 <span className="truth-label truth-observed">实测</span></div>
            <table className="latent-stats-table">
              <thead><tr><th>通道</th><th>最小</th><th>最大</th><th>均值</th><th>标准差</th><th>L2</th></tr></thead>
              <tbody>{channels.map((channel) => <tr key={channel.channel}><td>C{channel.channel}</td><td>{formatLatentMetric(channel.min)}</td><td>{formatLatentMetric(channel.max)}</td><td>{formatLatentMetric(channel.mean)}</td><td>{formatLatentMetric(channel.std)}</td><td>{formatLatentMetric(channel.l2)}</td></tr>)}</tbody>
            </table>
          </div>
        <div className="latent-histogram-wrap">
            <div className="section-title">直方图 <span className="truth-label truth-observed">四通道 · 实测</span></div>
            <div className="latent-histogram-grid">
              {channels.map((channel) => {
                const maximum = Math.max(1, ...channel.histogram);
                return <div key={channel.channel}><span>C{channel.channel}</span><div className="latent-histogram" role="img" aria-label={`通道 C${channel.channel} 直方图`}>{channel.histogram.map((value, index) => <span key={index} title={`${index}: ${value}`} style={{ height: `${Math.max(3, (value / maximum) * 100)}%` }} />)}</div></div>;
              })}
            </div>
          </div>
        </div>
      </> : <div className="unavailable-panel"><strong>四通道 Latent 检查器不可用</strong><p>当前步骤没有完整导出 C0–C3 的真实通道数据。</p></div>}

      <CorrelationMatrix sample={sample} />
      <LatentDeltaImage sample={sample} />
      <SelectedChannelComparison previous={previous} current={sample} final={final} />

      <div className="latent-step-comparison">
        <div className="section-title">步骤对比 <small>上一步 / 当前 / 最终</small></div>
        <div className="latent-step-comparison-grid">
          {[{ label: "上一步", value: previous }, { label: "当前", value: sample }, { label: "最终", value: final }].map((entry) => (
            <div key={entry.label} aria-label={`${entry.label} Latent`}><span>{entry.label}</span><strong>{entry.value ? `第 ${entry.value.step + 1} 步` : "—"}</strong><small>{entry.value ? `均值 ${formatLatentMetric(entry.value.mean)} · 标准差 ${formatLatentMetric(entry.value.std)}` : "尚未采集"}</small></div>
          ))}
        </div>
      </div>
    </div>
  );
}

function formatLatentMetric(value: number | null | undefined): string {
  return value === null || value === undefined || !Number.isFinite(value) ? "—" : value.toFixed(4);
}

function AttentionPanel({ runId, capability, researchStatus, index, indexMessage, captureContext, indexLoading }: { runId: string; capability: RuntimeCapabilities["attention"] | null; researchStatus: ResearchStatus | null; index: RuntimeAttentionIndex | null; indexMessage: string; captureContext: CaptureContext; indexLoading: boolean }) {
  const provider = useDreamProvider();
  const [selectedMapId, setSelectedMapId] = useState<string | null>(null);
  const [attentionMap, setAttentionMap] = useState<RuntimeAttentionMap | null>(null);
  const [mapMessage, setMapMessage] = useState(indexMessage);

  useEffect(() => {
    setAttentionMap(null);
    const firstMap = index?.available ? index.maps[0] : null;
    setSelectedMapId(firstMap?.id ?? null);
    setMapMessage(firstMap ? "已读取实测 cross-attention 索引。" : indexMessage);
  }, [index, indexMessage]);

  useEffect(() => {
    if (!selectedMapId) {
      setAttentionMap(null);
      return;
    }
    let active = true;
    setAttentionMap(null);
    void provider.getAttentionMap(runId, selectedMapId).then((value) => {
      if (active) setAttentionMap(value);
    }).catch((reason: unknown) => {
      if (!active) return;
      setAttentionMap(null);
      setMapMessage(reason instanceof Error ? reason.message : "所选 H7 热力图不可用");
    });
    return () => { active = false; };
  }, [provider, runId, selectedMapId]);

  const message = mapMessage || indexMessage;

  const boundaryMessage = captureMessage(captureContext, "H7", indexMessage, indexLoading);
  const availableIndex = index?.available ? index : null;
  const selectedDescriptor = availableIndex?.maps.find((entry) => entry.id === selectedMapId) ?? null;
  const selectedToken = selectedDescriptor ? availableIndex?.tokens.find((entry) => entry.slot === selectedDescriptor.tokenSlot) ?? null : null;
  const selectedLayer = selectedDescriptor ? availableIndex?.layers.find((entry) => entry.id === selectedDescriptor.layerId) ?? null : null;
  const selectableTokens = availableIndex?.tokens.filter((token) => availableIndex.maps.some((entry) => entry.tokenSlot === token.slot)) ?? [];
  const attentionRange = attentionMap ? attentionValueRange(attentionMap.values) : null;

  const selectDescriptor = (predicate: (entry: RuntimeAttentionMapDescriptor) => boolean, preferred?: (entry: RuntimeAttentionMapDescriptor) => boolean) => {
    const next = availableIndex?.maps.find((entry) => predicate(entry) && (preferred?.(entry) ?? true)) ?? availableIndex?.maps.find(predicate);
    if (next) setSelectedMapId(next.id);
  };

  if (availableIndex) {
    return (
      <div className="attention-layout">
        <div className="surface-card attention-main attention-workbench">
          <div className="research-banner">ⓘ　当前显示研究引擎采集的 Cross-attention。聚合值来自已采集记录；区域比较按需读取同层、同一步骤的 Token。</div>
          {availableIndex.source === "diffusers-unet" && <p className="research-banner">人物引擎：从实测 Q/K 以 FP32 softmax 重算条件分支文本注意力，再对多头取均值；不是逐头转储，也不是 FaceID 图像条件本身。当前 {availableIndex.layers.length} 层、{new Set(availableIndex.maps.map(entry => entry.step)).size} 步、{availableIndex.tokens.length} 个文本 Token。</p>}
          <div className="section-title">{attentionMap ? "H7 注意力工作台" : "正在准备 H7 注意力工作台…"} <span className="truth-label truth-observed">Cross-attention · 实测</span></div>
          <div className="h7-workbench-grid">
            <section className="h7-token-panel" aria-label="Attention Token 列表">
              <strong>Token 与提示词权重</strong><p className="muted-copy">右侧数值为输入权重，不是注意力强度。</p>
              <div className="h7-token-list">
                {selectableTokens.map((token) => <button type="button" key={token.slot} className={token.slot === selectedToken?.slot ? "is-selected" : ""} aria-label={`选择 token ${token.text}`} aria-pressed={token.slot === selectedToken?.slot} onClick={() => selectDescriptor((entry) => entry.tokenSlot === token.slot, (entry) => entry.step === selectedDescriptor?.step && entry.layerId === selectedDescriptor?.layerId)}><span>{String(token.slot).padStart(4, "0")}</span><b>{token.text}</b><small>{token.weight.toFixed(2)}</small></button>)}
              </div>
            </section>
            <section className="h7-map-panel">
              <div className="h7-map-controls">
                <label>层<select aria-label="注意力层" value={selectedDescriptor?.layerId ?? ""} onChange={(event) => selectDescriptor((entry) => entry.tokenSlot === selectedToken?.slot && entry.layerId === event.target.value, (entry) => entry.step === selectedDescriptor?.step)}>{availableIndex.layers.filter((layer) => availableIndex.maps.some((entry) => entry.tokenSlot === selectedToken?.slot && entry.layerId === layer.id)).map((layer) => <option key={layer.id} value={layer.id}>{layer.label}</option>)}</select></label>
                <label>去噪步骤<select aria-label="注意力步骤" value={selectedDescriptor?.id ?? ""} onChange={(event) => setSelectedMapId(event.target.value)}>{availableIndex.maps.filter((entry) => entry.tokenSlot === selectedToken?.slot && entry.layerId === selectedDescriptor?.layerId).map((entry) => <option key={entry.id} value={entry.id}>第 {entry.step + 1} 步</option>)}</select></label>
              </div>
              {attentionMap && selectedToken && selectedLayer ? <>
                <div className="h7-heatmap" role="img" aria-label={`${selectedToken.text} 在 ${selectedLayer.label} 第 ${attentionMap.step + 1} 步的注意力热力图`} data-attention-heatmap="observed" style={{ gridTemplateColumns: `repeat(${attentionMap.width}, minmax(0, 1fr))` }}>
                  {attentionMap.values.map((value, cellIndex) => {
                    const displayIntensity = attentionRange ? normalizeAttentionValue(value, attentionRange.minimum, attentionRange.maximum) : 0;
                    return <span key={cellIndex} aria-hidden="true" title={`实测 ${value.toFixed(4)} · 显示强度 ${displayIntensity.toFixed(4)}`} data-display-intensity={displayIntensity.toFixed(4)} style={{ background: attentionCellColor(displayIntensity) }} />;
                  })}
                </div>
                <div className="h7-map-caption"><span>{selectedToken.text}</span><span>{selectedLayer.label}</span><span>第 {attentionMap.step + 1} 步</span><span>{attentionMap.width} × {attentionMap.height}</span></div>
                {attentionRange ? <p className="h7-color-scale">色阶按当前图实测范围 {attentionRange.minimum.toFixed(4)}–{attentionRange.maximum.toFixed(4)} 归一化</p> : null}
              </> : <div className="attention-map-loading">{message}</div>}
            </section>
          </div>
        </div>
        <aside className="surface-card focused-card h7-statistics">
          <div className="section-title">焦点与统计 <span className="truth-label truth-observed">实测</span></div>
          {attentionMap && selectedToken && selectedLayer ? <>
            <div className="h7-selection"><span>所选 Token</span><strong>{selectedToken.text}</strong><small>ID {selectedToken.tokenId} · Chunk {selectedToken.chunk + 1}</small></div>
            <div className="h7-stat-list"><div><span>峰值注意力</span><strong>{attentionMap.peak.toFixed(3)}</strong></div><div><span>注意力熵</span><strong>{attentionMap.entropy.toFixed(3)}</strong></div><div><span>覆盖率</span><strong>{attentionMap.coverage.toFixed(3)}</strong></div></div>
            <div className="h7-evidence"><strong>证据边界</strong><p>来源：{availableIndex.source}</p><p>契约：{availableIndex.contractVersion}</p><p>运行：{availableIndex.runId}</p></div>
          </> : <div className="empty-state"><span className="empty-icon">⌕</span><span>{message}</span></div>}
        </aside>
        <div className="h7-analysis-full"><AttentionAnalysis key={runId} index={availableIndex} map={attentionMap} onSelect={setSelectedMapId} /></div>
      </div>
    );
  }

  return (
    <div className="attention-layout">
      <div className="surface-card attention-main">
        <div className="research-banner">ⓘ　能力与研究引擎状态用于说明采集条件；实际显示以所选记录中有效的实测张量为准。</div>
        <div className="section-title">H7 注意力探索器 <span className="truth-label truth-unavailable">Attention 张量不可用</span></div>
        <h2>检查提示词如何影响图像。</h2>
        {captureContext.route !== "visual" && <div className="h7-status-grid">
          <div><span>全局生产能力（不代表当前任务路线）</span><strong>{localizeResearchMessage(capability?.message ?? "Attention 能力状态不可用")}</strong><small>{capability?.available ? "已声明可用" : "不可用"}</small></div>
          <div><span>全局研究引擎</span><strong>{localizeResearchMessage(researchStatus?.message ?? "研究状态不可用")}</strong><small>{researchStatus?.available ? "已连接" : "不可用"}</small></div>
        </div>}
        <div className="attention-empty"><strong>Cross-attention 张量不可用</strong><p role="status">{boundaryMessage}</p><p>{indexMessage}</p><p>没有真实 token × step × layer 张量时，不显示伪造热力图。</p></div>
      </div>
      <aside className="surface-card focused-card">
        <div className="section-title">焦点区域与统计</div>
        <div className="empty-state"><span className="empty-icon">⌕</span><span>选择真实 attention 记录后查看 token 区域。</span></div>
      </aside>
    </div>
  );
}

function attentionCellColor(value: number): string {
  const bounded = Math.min(1, Math.max(0, value));
  const hue = 232 - bounded * 232;
  const lightness = 18 + bounded * 42;
  return `hsl(${hue.toFixed(0)} 92% ${lightness.toFixed(0)}%)`;
}

function localizeResearchMessage(message: string): string {
  if (/No native runtime trace is available/i.test(message)) return "暂无原生运行记录，请先完成一次生成。";
  if (/No validated native H7 attention trace/i.test(message)) return "当前运行没有有效的 H7 注意力数据。";
  if (/[\u3400-\u9fff]/.test(message)) return message;
  return "当前研究数据不可用。请刷新记录并检查所选记录的采集级别；原始信息可在日志中查看。";
}

function attentionValueRange(values: number[]): { minimum: number; maximum: number } {
  if (!values.length) return { minimum: 0, maximum: 0 };
  return values.reduce(
    (range, value) => ({ minimum: Math.min(range.minimum, value), maximum: Math.max(range.maximum, value) }),
    { minimum: values[0], maximum: values[0] },
  );
}

function normalizeAttentionValue(value: number, minimum: number, maximum: number): number {
  const range = maximum - minimum;
  if (!Number.isFinite(range) || range <= Number.EPSILON) return 0;
  return Math.min(1, Math.max(0, (value - minimum) / range));
}

function Metric({ label, value }: { label: string; value: string }) {
  return <div className="metric-card"><span>{label}</span><strong>{value}</strong></div>;
}

function formatSeconds(milliseconds: number): string {
  return (milliseconds / 1000).toFixed(1) + " 秒";
}

function phaseLabel(value: string): string {
  const labels: Record<string, string> = {
    Conditioning: "条件编码",
    "UNet sampling": "UNet 采样",
    "VAE decode": "VAE 解码",
    "Image generation": "图像生成",
  };
  return labels[value] ?? value;
}

function formatDuration(milliseconds: number): string {
  return Math.round(milliseconds).toLocaleString("zh-CN") + " 毫秒";
}

function eventWidth(durationMs: number, totalTimeMs: number): string {
  const width = totalTimeMs > 0 ? (durationMs / totalTimeMs) * 100 : 4;
  return Math.min(100, Math.max(4, width)) + "%";
}

function truthLabel(value: RuntimeNode["truth"]): string {
  return value === "observed" ? "实测" : value === "derived" ? "派生" : value === "demo" ? "演示" : "不可用";
}

function statusLabel(value: RuntimeNode["status"]): string {
  return value === "executed" ? "已执行" : value === "running" ? "运行中" : value === "error" ? "错误" : "已跳过";
}

function formatMiB(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : value.toLocaleString("zh-CN") + " MiB";
}

function formatMiBNumber(value: number): string {
  return value.toLocaleString("zh-CN");
}

function formatBytePair(used: number, total: number): string {
  if (used >= 1024 ** 3 || total >= 1024 ** 3) return `${(used / 1024 ** 3).toFixed(1)} / ${(total / 1024 ** 3).toFixed(1)} GiB`;
  return `${Math.round(used / 1024 ** 2).toLocaleString("zh-CN")} / ${Math.round(total / 1024 ** 2).toLocaleString("zh-CN")} MiB`;
}

function formatBytes(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  if (value >= 1024 ** 3) return (value / 1024 ** 3).toFixed(1) + " GiB";
  return Math.round(value / 1024 ** 2).toLocaleString("zh-CN") + " MiB";
}
