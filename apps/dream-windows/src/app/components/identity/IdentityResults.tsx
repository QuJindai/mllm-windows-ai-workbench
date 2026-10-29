import { useEffect, useRef, useState } from "react";
import { identityJobSeed, identityModelName, identityReferenceKind, identityStateLabels, isIdentityJobActive } from "../../../domain/identity";
import type { IdentityBatch, IdentityJob, IdentityProfile, IdentityReference, VisualPolishSnapshot } from "../../../domain/identity";
import { identityApi } from "../../../providers/identity-api";
import { DeleteImageButton } from "../DeleteImageButton";
import { useDeletedImageIds } from "../../image-deletion";
import { RefinementWorkspace } from "./RefinementWorkspace";

export function ResultPreview({ imageUrl, label = "生成结果" }: { imageUrl: string; label?: string }) {
  const [unavailable, setUnavailable] = useState(false);
  return <figure>
    {unavailable ? <div className="identity-empty" role="status">结果文件已删除或不可用</div>
      : <a href={imageUrl} target="_blank" rel="noreferrer"><img src={imageUrl} alt={label} onError={() => setUnavailable(true)} /></a>}
    <figcaption>{unavailable ? label : `${label} · 点击查看完整图像`}</figcaption>
  </figure>;
}

const polishStageLabels = { anchor: "对齐预览", harmonize: "第一轮融合", detail: "第二轮细化" } as const;

function FacePolishPreview({ job }: { job: IdentityJob & { result: NonNullable<IdentityJob["result"]> } }) {
  const [selection, setSelection] = useState<"original" | "final" | VisualPolishSnapshot["kind"]>("final");
  const polish = job.result.metadata.facePolish;
  const visual = identityReferenceKind(job.request.modelId) === "visual";
  const operation = visual ? "局部重绘" : "修脸";
  const resultLabel = visual ? "重绘结果" : "修脸结果";
  const failed = polish?.status === "failed";
  const completed = job.state === "complete" && polish?.enabled === true && polish.status === "completed";
  if (!failed && !completed) return <>
    {job.result.metadata.facePolishValidationError
      ? <p className="identity-error" role="alert">{job.result.metadata.facePolishValidationError}</p>
      : job.request.facePolish && <p className="identity-note">未返回{operation}完成记录，以下为生成结果。</p>}
    <ResultPreview key={job.result.imageUrl} imageUrl={job.result.imageUrl} />
  </>;
  const originalUrl = polish?.originalImageUrl || (failed ? job.result.imageUrl : `/api/identity/jobs/${encodeURIComponent(job.id)}/original`);
  // The output path may have been previewed before polishing. A stable completion
  // revision avoids that cache entry without busting the cache on every poll/render.
  const [path, fragment] = job.result.imageUrl.split("#", 2);
  const finalUrl = `${path}${path.includes("?") ? "&" : "?"}identityResult=${encodeURIComponent(`${job.id}:${polish?.status}`)}${fragment ? `#${fragment}` : ""}`;
  const protectedFace = visual && completed && polish?.detailerVersion === "protected-face-v3" && polish.featureProtection === "central-features-v1";
  const staged = visual && completed && (polish?.detailerVersion === "staged-face-v2" || protectedFace);
  const snapshots = staged ? polish.snapshots ?? [] : [];
  const snapshot = snapshots.find(stage => stage.kind === selection);
  const showOriginal = selection === "original";
  const imageUrl = failed || showOriginal ? originalUrl : snapshot?.imageUrl ?? finalUrl;
  const label = failed ? "保留的原图" : showOriginal ? "生成原图" : snapshot ? polishStageLabels[snapshot.kind] : resultLabel;
  return <section className="identity-polish-result" aria-label={`原图与${resultLabel} ${job.id}`}>
    {failed ? <div className="identity-error identity-polish-failure" role="alert">
      <strong>{operation}失败，已保留原图</strong><p>{polish?.message || "服务未返回具体失败原因。"}</p>
    </div> : <p className="identity-polish-complete">{operation}完成{visual ? " · 当前视觉参考" : polish?.method === "anime-reference-local-redraw" ? ` · ${polish.profileName} · 动漫局部重绘` : ""}</p>}
    {visual && completed && <p className="identity-note">重绘强度 {polish?.denoiseStrength} · {polish?.outsideMaskUnchanged ? "掩膜外像素未改动" : "掩膜外像素有变化"}（服务记录）</p>}
    {staged && <>
      <p className="identity-note">模式：{polish.polishMode === "reference-anchor" ? "参考脸对齐" : "局部重绘"} · 已完成 {polish.passes?.length} 轮</p>
      {protectedFace && <p className="identity-polish-complete">五官保护 v3 · 保留中央五官，仅融合边缘（服务记录）</p>}
      {polish.polishMode === "reference-anchor" && <p className="identity-note">参考脸融合强度 {polish.anchorStrength} · 几何对齐误差 {polish.alignmentError}（按眼距归一化，仅衡量位置拟合）</p>}
      <table aria-label="修脸分轮实测记录"><thead><tr><th>轮次</th><th>去噪强度</th><th>实测步数</th><th>实测耗时</th></tr></thead>
        <tbody>{polish.passes?.map(pass => <tr key={pass.kind}><td>{polishStageLabels[pass.kind]}</td><td>{pass.denoiseStrength}</td><td>{pass.steps}</td><td>{(pass.durationMs / 1000).toFixed(2)} 秒</td></tr>)}</tbody>
      </table>
      <p className="identity-note">请对照原图与可用阶段图选择；第二轮不一定更好。</p>
    </>}
    {completed && <div className="identity-actions" role="group" aria-label="选择结果图像">
      <button type="button" className="secondary-button" aria-pressed={showOriginal} onClick={() => setSelection("original")}>查看生成原图</button>
      {snapshots.map(stage => <button key={stage.kind} type="button" className="secondary-button" aria-pressed={selection === stage.kind}
        onClick={() => setSelection(stage.kind)}>{polishStageLabels[stage.kind]}</button>)}
      <button type="button" className="secondary-button" aria-pressed={!showOriginal && !snapshot} onClick={() => setSelection("final")}>查看{resultLabel}</button>
    </div>}
    <ResultPreview key={`${label}:${imageUrl}`} imageUrl={imageUrl} label={label} />
    <div className="identity-actions">
      <a className="identity-result-link" href={originalUrl} target="_blank" rel="noreferrer">打开生成原图</a>
      {completed && <a className="identity-result-link" href={finalUrl} target="_blank" rel="noreferrer">打开{resultLabel}</a>}
    </div>
  </section>;
}

function JobResultPreview({ job }: { job: IdentityJob }) {
  if (!job.result) return null;
  const research = job.result.metadata.research;
  const researchFailed = !!research && typeof research === "object" && "status" in research && research.status === "failed";
  return <>
    {researchFailed && <div className="identity-error" role="alert"><strong>研究采集失败，图片已保留</strong><p>本次显微镜结果不可用，可查看任务元数据和日志；生成图片仍可使用。</p></div>}
    <FacePolishPreview key={`${job.id}:${job.result.imageUrl}:${job.result.metadata.facePolish?.status}:${job.result.metadata.facePolish?.originalImageUrl}`} job={{ ...job, result: job.result }} />
  </>;
}

function MeasuredStages({ metadata }: { metadata: Record<string, unknown> }) {
  const stages = Array.isArray(metadata.stages) ? metadata.stages.filter((stage): stage is { name: string; durationMs: number; truth: "observed" } =>
    !!stage && typeof stage === "object" && stage.truth === "observed" && typeof stage.name === "string" && typeof stage.durationMs === "number" && Number.isFinite(stage.durationMs) && stage.durationMs >= 0) : [];
  const memory = (value: unknown) => typeof value === "number" && Number.isFinite(value) && value >= 0 ? `${value} MiB` : "未返回";
  const duration = metadata.generation_time_ms;
  return <div className="identity-measurements">
    {stages.length ? <table aria-label="实测阶段耗时"><thead><tr><th>阶段</th><th>实测耗时</th></tr></thead><tbody>{stages.map((stage, index) => <tr key={`${stage.name}-${index}`}><td>{stage.name}</td><td>{(stage.durationMs / 1000).toFixed(2)} 秒</td></tr>)}</tbody></table> : <p className="identity-note">阶段耗时：未返回实测记录</p>}
    <p className="identity-note">峰值已分配显存：{memory(metadata.peakAllocatedMiB)}</p>
    <p className="identity-note">峰值保留显存：{memory(metadata.peakReservedMiB)}</p>
    <p className="identity-note">推理阶段合计：{typeof duration === "number" && Number.isFinite(duration) && duration >= 0 ? `${(duration / 1000).toFixed(2)} 秒` : "未返回"}（不含工作进程启动）</p>
    <p className="identity-note">特征缓存：{metadata.cacheHit === true ? "命中" : metadata.cacheHit === false ? "未命中" : "未返回"}</p>
  </div>;
}

function Measurements({ job }: { job: IdentityJob | null }) {
  const visual = identityReferenceKind(job?.request.modelId) === "visual";
  const research = job?.result?.metadata.research as { h6?: boolean; h7?: boolean; runId?: string; latentSteps?: number; coverage?: string } | undefined;
  const hasTrace = !!job?.result && research?.runId === job.id && (research.h6 || research.h7 || (research.latentSteps ?? 0) > 0);
  return <div className="identity-metadata">
    {job && <p className="identity-note">任务底模：{identityModelName(job.request.modelId)}</p>}
    <p className="identity-note">H6 条件影响：{visual ? "视觉参考不可用" : research?.h6 ? "已采集 · 身份条件干预" : "未采集"}</p><p className="identity-note">H7 自/交叉注意力：{visual ? "视觉参考不可用" : research?.h7 ? "已采集 · 多头均值" : "未采集"}</p>
    {hasTrace && <a className="identity-result-link" href={`/?view=microscope&run=${encodeURIComponent(job!.id)}`} target="_blank" rel="noreferrer">在显微镜打开此任务</a>}
    {job?.result ? <><MeasuredStages metadata={job.result.metadata} /><details><summary>实际任务元数据</summary><pre>{JSON.stringify(job.result.metadata, null, 2)}</pre></details></> : <p className="identity-note">阶段耗时与显存等待服务返回；当前没有实测产物。</p>}
  </div>;
}

function IntermediatePreview({ url }: { url: string }) {
  const [unavailable, setUnavailable] = useState(false);
  return <figure className="identity-intermediate">{unavailable ? <p className="identity-note">中间预览暂不可用，生成仍会继续。</p> : <img src={url} alt="采样中间预览" onError={() => setUnavailable(true)} />}<figcaption>采样中间预览（去噪预测，非最终成图）</figcaption></figure>;
}

function ReferenceImage({ reference, faceIndex }: { reference?: IdentityReference; faceIndex?: number }) {
  return <figure>{reference ? <img src={reference.imageUrl} alt="任务参考照" /> : <div className="identity-empty">暂无任务参考照</div>}<figcaption>参考人物{faceIndex !== undefined ? ` · 人脸 ${faceIndex + 1}` : ""}</figcaption></figure>;
}

type Props = {
  batch: IdentityBatch | null; job: IdentityJob | null; reference?: IdentityReference; profile: IdentityProfile | null;
  opening: boolean; cancelling: boolean; pending: boolean; pollError: string | null;
  onCancel: () => void; onSavePreset: (job: IdentityJob) => void;
};
const seconds = (ms: number) => Number.isFinite(ms) && ms >= 0 ? `${(ms / 1000).toFixed(1)} 秒` : "未返回";
function remainingTime(batch: IdentityBatch): string {
  if (batch.state === "complete") return "已完成";
  if (batch.state === "cancelled") return "已停止（已取消）";
  if (batch.state === "failed") return "已停止（失败）";
  return batch.state === "sampling" && batch.step > 0 && typeof batch.etaMs === "number" && Number.isFinite(batch.etaMs) && batch.etaMs >= 0
    ? `${seconds(batch.etaMs)}（估计）` : "暂无可靠估计";
}

export function IdentityResults({ batch, job, reference, profile, opening, cancelling, pending, pollError, onCancel, onSavePreset }: Props) {
  const deletedImages = useDeletedImageIds();
  const [refiningId, setRefiningId] = useState<string | null>(null);
  const isDeleted = (item: IdentityJob) => item.resultDeleted || item.historyDeleted || deletedImages.has(item.id);
  const observationHeading = useRef<HTMLHeadingElement>(null);
  const lastFocusedBatch = useRef<string | undefined>(undefined);
  const batchId = batch?.id;
  useEffect(() => {
    if (!batchId) { lastFocusedBatch.current = undefined; return; }
    if (lastFocusedBatch.current === batchId) return;
    lastFocusedBatch.current = batchId;
    const heading = observationHeading.current;
    // Polls keep the same ID; a batch accepted while this page is hidden must not steal focus.
    if (!heading || heading.closest("[hidden]")) return;
    heading.focus({ preventScroll: true });
    heading.scrollIntoView?.({ block: "start", behavior: "auto" });
  }, [batchId]);
  if (batch && (batch.historyDeleted || deletedImages.has(batch.id))) {
    return <section className="surface-card identity-results" aria-label="人物任务详情"><h2>批次观察</h2><p role="status">批次已删除，人物档案与参考照片保留。</p><ReferenceImage reference={reference} faceIndex={batch.request.request.faceIndex} /></section>;
  }
  const completed = batch?.items.filter((item) => item.state === "complete" && item.result && !isDeleted(item)) ?? [];
  const refinementSource = (batch ? completed : job ? [job] : []).find(item => item.id === refiningId && item.state === "complete" && item.result && !isDeleted(item));
  const refineButton = (item: IdentityJob) => item.id.startsWith("identity-") && <button type="button" className="secondary-button" disabled={pending || opening} onClick={() => setRefiningId(item.id)}>独立精修</button>;
  const saveButton = (item: IdentityJob) => <button type="button" className="secondary-button" aria-label={`将 ${item.id} 存为人物预设`}
    disabled={pending || opening || profile?.state !== "ready" || profile.referenceId !== item.request.referenceId || profile.faceIndex !== item.request.faceIndex}
    onClick={() => onSavePreset(item)}>将此图参数存为人物预设</button>;
  return <div className="identity-results">
    <section className="surface-card identity-job" aria-label="人物任务详情">
      <h2 ref={observationHeading} tabIndex={batch ? -1 : undefined}>{batch ? "批次观察" : "任务状态"}</h2>
      {opening && <p role="status">正在打开人物任务…</p>}
      {batch ? <>
        <div role="status" aria-label="批次进度"><strong>{identityStateLabels[batch.state]}</strong> · 第 {batch.currentItem} / {batch.totalItems} 张 · 已完成 {batch.completedItems} 张</div>
        <p>当前阶段：{batch.stage || "等待服务返回"}</p>
        {batch.step > 0 && batch.totalSteps > 0 && <p>{batch.step} / {batch.totalSteps} 步</p>}
        <p>已用时间：{seconds(batch.elapsedMs)}（实测）</p>
        <p>预计剩余：{remainingTime(batch)}</p>
        {isIdentityJobActive(batch) && <button type="button" className="danger-button" disabled={pending || opening} onClick={onCancel}>{cancelling ? "正在取消…" : "取消批次"}</button>}
        <p className="identity-note">取消只停止当前及剩余未完成项，已完成结果保留。</p>
        {batch.error && <p role="alert" className="identity-error">{batch.error}</p>}
      </> : job ? <>
        <div aria-label="当前任务状态" role="status"><strong>{identityStateLabels[job.state]}</strong> · {job.message}</div>
        <p className="identity-note">任务 {job.id} · 服务进度：{job.progress}</p>
        {isIdentityJobActive(job) && <button className="danger-button" type="button" disabled={pending || opening} onClick={onCancel}>{cancelling ? "正在取消…" : "取消人物任务"}</button>}
        {job.error && <p role="alert" className="identity-error">{job.error}</p>}
        <p>实际种子：{identityJobSeed(job) === "random" ? "尚未返回" : identityJobSeed(job)}</p>
      </> : <p className="identity-note">选择参考人物并提交后，这里将显示真实任务状态。</p>}
      {pollError && <p role="alert" className="identity-error">{pollError}</p>}
    </section>
    <section className="surface-card identity-comparison" aria-label="参考与结果对照">
      <h2>参考 / {batch ? "中间预览" : "结果"}对照</h2>
      <div className="identity-images">
        <ReferenceImage reference={reference} faceIndex={batch?.request.request.faceIndex ?? job?.request.faceIndex} />
        {batch ? batch.request.previewEvery !== 0 && batch.previewUrl ? <IntermediatePreview key={`${batch.id}:${batch.previewUrl}`} url={batch.previewUrl} /> : <p className="identity-note">{batch.request.previewEvery === 0 ? "中间预览已关闭" : "等待服务返回中间预览"}</p>
          : job && isDeleted(job) ? <p role="status">{job.resultDeleted ? "图片已删除，仍可复用生成参数。" : "历史记录已删除，仍可复用生成参数。"}</p> : job?.result?.imageUrl ? <div><JobResultPreview job={job} />{job.state === "complete" && refineButton(job)}{job.state === "complete" && <DeleteImageButton key={job.id} id={job.id} disabled={pending || opening} onDelete={identityApi.deleteJob} />}</div> : <figure><div className="identity-empty">结果尚未生成</div><figcaption>生成结果</figcaption></figure>}
      </div>
    </section>
    {batch ? <section className="surface-card" aria-label="已完成结果"><h2>已完成结果 · {completed.length} 张</h2>
      <div className="identity-completed-grid">{completed.map((item) => <article className="identity-result-card" key={item.id} aria-label={`已完成结果 ${item.id}`}>
        <JobResultPreview job={item} />
        <p>种子 {identityJobSeed(item)} · {item.request.steps} 步</p>
        <p className="identity-note">{item.id}</p>{saveButton(item)}{refineButton(item)}
        <DeleteImageButton id={item.id} disabled={pending || opening} onDelete={identityApi.deleteJob} />
        <details><summary>查看实测过程</summary><Measurements job={item} /></details>
      </article>)}</div>
      {!completed.length && <p className="identity-note">{batch.items.some(isDeleted) ? "已完成的图片已删除，任务参数仍保留。" : "尚无已完成结果，完成的原图会逐张保留在这里。"}</p>}
      {!profile && completed.length > 0 && <p className="identity-note">本批未绑定人物档案，不能保存人物预设。可用原参考照创建档案后，打开这张历史任务保存参数。</p>}
    </section> : <section className="surface-card"><h2>实测过程</h2><Measurements job={job} />{job?.state === "complete" && job.result && saveButton(job)}</section>}
    {refinementSource && <RefinementWorkspace sourceJobId={refinementSource.id} onClose={() => setRefiningId(null)} />}
  </div>;
}
