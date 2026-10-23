import { useEffect, useMemo, useState } from "react";
import { identityReferenceKind, isIdentityModelId } from "../../domain/identity";
import type { GenerationJob } from "../../domain/generation";
import type { IdentityJob } from "../../domain/identity";
import type { RuntimeInfluence, RuntimeSelfAttentionIndex } from "../../domain/trace";
import { identityApi } from "../../providers/identity-api";
import { DreamProviderContext, useDreamProvider } from "../providers";
import { InfluencePanel } from "../components/InfluencePanel";
import { SelfAttentionPanel } from "../components/SelfAttentionPanel";

export function useCaptureContext(runId: string | null, modelId: string | undefined, refreshVersion: number) {
  const provider = useDreamProvider();
  const [record, setRecord] = useState<{ runId: string; job: IdentityJob | GenerationJob | null } | null>(null);
  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    setRecord(null);
    if (runId) {
      const request = runId.startsWith("identity-") ? identityApi.job(runId, controller.signal) : provider.getJob(runId);
      void request.then(job => {
        if (active) setRecord({ runId, job: job.id === runId && job.request ? job : null });
      }).catch(() => { if (active) setRecord({ runId, job: null }); });
    }
    return () => { active = false; controller.abort(); };
  }, [provider, runId, refreshVersion]);
  const current = record?.runId === runId ? record : null;
  const job = current?.job;
  const selectedModel = modelId ?? job?.request.modelId;
  const route = identityReferenceKind(selectedModel) === "visual" ? "visual"
    : selectedModel && isIdentityModelId(selectedModel) ? "faceid"
      : runId?.startsWith("job-") && job ? "native" : "unknown";
  const research = job?.result?.metadata.research;
  const publicationFailed = !!research && typeof research === "object" && "status" in research && research.status === "failed";
  return { route, loading: !!runId && !current, traceLevel: job?.request.traceLevel, publicationFailed };
}
export type CaptureContext = ReturnType<typeof useCaptureContext>;

// A missing tensor alone cannot tell us whether capture was disabled or failed.
// Only a matching persisted job can supply that distinction; artifacts still take precedence.
export function captureMessage(context: CaptureContext, level: "H6" | "H7", artifactMessage = "", loading = false) {
  const traceLevel = context.traceLevel;
  const enabled = traceLevel === "h7" || level === "H6" && traceLevel === "h6";
  if (context.publicationFailed && enabled) return `${level} 采集失败：任务记录确认研究产物发布失败。请检查任务错误与日志，修复后重新采集；已生成图片仍保留。`;
  if (/读取失败|接口.*不可用|无效|不一致/.test(artifactMessage)) return `${level} 记录读取失败或校验未通过。请刷新记录并检查产物；无法据此判断本次是否完成采集。`;
  if (context.loading || loading) return `正在核对本次任务的 ${level} 采集记录…`;
  if (!["off", "basic", "h6", "h7"].includes(traceLevel ?? "")) return `无法确认本次任务的 ${level} 采集设置。请选择已有实测记录，或检查原任务记录；缺少张量不代表未启用。`;
  if (enabled) return `本次任务已启用 ${level}，但未取得有效采集产物。请检查任务是否完成、产物是否缺失或无效，再刷新记录。`;
  if (context.route === "visual") return `本次视觉参考任务未启用 ${level}。请在人物创作中启用代表研究采集后重新生成；旧记录无法补出张量。`;
  const guidance = context.route === "faceid" ? `请在人物创作中启用 ${level} 研究采集后重新生成。`
    : context.route === "native" ? `请在生成页启用 ${level} 研究采集后重新生成。`
      : "当前路线的采集能力尚未确认，请检查原任务记录。";
  return `本次任务未启用 ${level} 研究采集。${guidance}`;
}

// Resolve absence before mounting the existing artifact viewers, whose generic
// empty states cannot distinguish routes. Their validation and map rendering stay intact.
export function RecordedResearchPanel({ kind, runId, context, cfg }: {
  kind: "influence" | "self"; runId: string | null; context: CaptureContext; cfg?: number;
}) {
  const provider = useDreamProvider();
  const [record, setRecord] = useState<RuntimeInfluence | RuntimeSelfAttentionIndex | null>(null);
  useEffect(() => {
    let active = true;
    setRecord(null);
    if (runId) {
      const request = kind === "influence" ? provider.getInfluence(runId) : provider.getSelfAttentionIndex(runId);
      void request.then(value => {
        if (active) setRecord(value.runId === runId ? value : { available: false, runId, truth: "unavailable", message: "研究记录与所选任务不一致" });
      }).catch(() => {
        if (active) setRecord({ available: false, runId, truth: "unavailable", message: "研究记录读取失败，请刷新记录。" });
      });
    }
    return () => { active = false; };
  }, [provider, runId, kind]);
  const current = record?.runId === runId ? record : null;
  // Reuse this exact validated response in the unmodified viewer. All other
  // reads (including selected maps) still use the real provider. Refresh remounts
  // this boundary, so the response never becomes a persistent cache.
  const recordedProvider = useMemo(() => new Proxy(provider, {
    get(target, property) {
      const value = Reflect.get(target, property, target);
      if (property === (kind === "influence" ? "getInfluence" : "getSelfAttentionIndex")) {
        return (requestedRunId: string) => current?.available && requestedRunId === current.runId
          ? Promise.resolve(current) : value.call(target, requestedRunId);
      }
      return typeof value === "function" ? value.bind(target) : value;
    },
  }), [provider, current, kind]);
  if (current?.available) return <DreamProviderContext.Provider value={recordedProvider}>
    {kind === "influence" ? <InfluencePanel runId={runId} cfg={cfg} /> : <SelfAttentionPanel runId={runId} />}
  </DreamProviderContext.Provider>;
  const level = kind === "influence" ? "H6" : "H7";
  const detail = current && !current.available ? current.message : "";
  return <section className="surface-card research-artifact-panel">
    <div className="section-title">{kind === "influence" ? "H6 条件影响" : "H7 自注意力"} <span className="truth-label truth-unavailable">张量不可用</span></div>
    <div className="unavailable-panel">
      <strong>{kind === "influence" ? "H6 条件影响张量不可用" : "Self-attention 未采集"}</strong>
      <p role="status">{captureMessage(context, level, detail, !current)}</p>
      {detail && /[\u3400-\u9fff]/.test(detail) && <p>{detail}</p>}
      <p>没有有效实测张量时不显示空间图。只有 Cross-attention 的旧记录不能提供自注意力空间锚点图。</p>
    </div>
    {kind === "influence" && <p>H6 是条件预测差异；不代表 Windows 生产路径对分块预测取算术平均，也不是人脸相似度评分。</p>}
  </section>;
}
