import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import type { HQAsset, HQCatalog, HQJob, HQParameters, HQPersonSource, HQRole, HQStatus } from "../../domain/hq-tryon";
import { defaultHQIdentity, defaultHQParameters, hqActive, hqBasisForPose, hqError, hqExecutionBasis, hqResolutionPresets, hqRoleLabels, hqRoles, hqStateLabels, isHQBasis, validHQParameters } from "../../domain/hq-tryon";
import type { IdentityJob, IdentityProfile, IdentityStatus } from "../../domain/identity";
import { identityStateLabels } from "../../domain/identity";
import { identityApi } from "../../providers/identity-api";
import { FacePolishControls } from "../components/identity/FacePolishControls";
import { JobResultPreview, ResultPreview } from "../components/identity/IdentityResults";
import { RefinementWorkspace } from "../components/identity/RefinementWorkspace";
import { refinementApi } from "../../providers/refinement-api";
import type { RefinementSnapshot } from "../../providers/refinement-api";
import { useDeletedImageIds } from "../image-deletion";
import { hqApi, hqFingerprint, readHQDraft, readHQOperations, reconcileHQOperations, reserveHQOperation, reserveHQRetry, retryableHQJob, saveHQOperation, writeHQDraft } from "../../providers/hq-tryon-api";
import type { HQOperation } from "../../providers/hq-tryon-api";
import { HQBodyRepair } from "./HQBodyRepair";
import "./HQTryOnPage.css";

const describe = (e: unknown) => e instanceof Error ? e.message : "本地服务请求失败";
const assetName = (asset: HQAsset) => asset.label || asset.name || asset.id;
const compatibleProfile = (p: IdentityProfile) => (p.defaults?.modelId ?? "realistic-vision-v5.1-faceid") === "realistic-vision-v5.1-faceid";
const shortId = (id: string) => id.length > 24 ? `${id.slice(0, 12)}…${id.slice(-6)}` : id;
type HQActionNotice = { jobId: string; kind: "submitted" | "cancel" | "copied" };
const phaseLabels: Record<string, string> = { downloading: "读取三图原图", identifying: "固定人物档案", identity_queued: "等待人物生成", queued: "等待本机资源", preparing: "固定人物与构图", sampling: "生成底图", generating: "生成底图", polishing: "可选换脸", face_polish: "可选换脸", "face-polish": "可选换脸", publishing: "保存成片", uploading: "保存成片", complete: "处理完成", succeeded: "处理完成", failed: "处理失败", cancelled: "已取消", interrupted: "运行中断" };

export function HQTryOnPage() {
  const deletedImages = useDeletedImageIds();
  const [draft] = useState(readHQDraft);
  const [selection, setSelection] = useState<Partial<Record<HQRole, HQAsset>>>(draft?.selection || {});
  const [parameters, setParameters] = useState<HQParameters>(draft?.parameters || defaultHQParameters);
  const [personSource, setPersonSource] = useState<HQPersonSource>(draft?.personSource ?? "gallery");
  const profileOnly = personSource === "profile";
  const [profileId, setProfileId] = useState(draft?.profileId || "");
  const [autoRepairEnabled, setAutoRepairEnabled] = useState(draft?.autoRepairEnabled ?? true);
  const [faceOptions, setFaceOptions] = useState({ facePolish: draft?.facePolish ?? defaultHQIdentity.facePolish, faceRestoreStrength: draft?.faceRestoreStrength ?? defaultHQIdentity.faceRestoreStrength });
  const [profiles, setProfiles] = useState<IdentityProfile[]>([]);
  const [selectedProfile, setSelectedProfile] = useState<IdentityProfile | null>(null);
  const [identityStatus, setIdentityStatus] = useState<IdentityStatus | null>(null);
  const [identityError, setIdentityError] = useState("");
  const [profileError, setProfileError] = useState("");
  const [profileLoading, setProfileLoading] = useState(false);
  const [kind, setKind] = useState<HQRole>(profileOnly ? "garment" : "person");
  const [search, setSearch] = useState("");
  const [filters, setFilters] = useState({ q: "", category: "", page: 0 });
  const [loadedCatalog, setLoadedCatalog] = useState<{ key: string; data: HQCatalog } | null>(null);
  const [catalogLoading, setCatalogLoading] = useState(false);
  const [catalogError, setCatalogError] = useState("");
  const [status, setStatus] = useState<HQStatus | null>(null);
  const [jobs, setJobs] = useState<HQJob[]>([]);
  const [activeId, setActiveId] = useState(draft?.activeJobId || "");
  const [job, setJob] = useState<HQJob | null>(null);
  const [linkedIdentity, setLinkedIdentity] = useState<IdentityJob | null>(null);
  const [linkedIdentityError, setLinkedIdentityError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [catalogRefresh, setCatalogRefresh] = useState(0);
  const [resultRefresh, setResultRefresh] = useState(0);
  const catalogKey = JSON.stringify([kind, filters.q, filters.category, filters.page, catalogRefresh]);
  // Never pair a new role/filter with old IDs, even in the commit before effects run.
  const canReadCatalog = status?.configured === true && (kind !== "person" || (!profileOnly && status.authorized));
  const catalog = canReadCatalog && loadedCatalog?.key === catalogKey ? loadedCatalog.data : null;
  const [loading, setLoading] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [jobsRevision, setJobsRevision] = useState(-1);
  const [detailRevision, setDetailRevision] = useState(-1);
  const [connectionError, setConnectionError] = useState("");
  const [detailError, setDetailError] = useState("");
  const [notice, setNotice] = useState<HQActionNotice | null>(null);
  const [actionError, setActionError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [cancelling, setCancelling] = useState<Set<string>>(new Set());
  const [reconciled, setReconciled] = useState(false);
  const submittingRef = useRef(false), pendingCreate = useRef<HQOperation | null>(null), cancellingRef = useRef(new Set<string>()), detailEpoch = useRef(0);
  const activeSelection = useRef({ id: activeId });
  const [resultUrl, setResultUrl] = useState("");
  const [resultError, setResultError] = useState("");
  const [, setReceiptVersion] = useState(0);
  const body = { ...(profileOnly ? { profileId } : { personId: selection.person?.id }), garmentId: selection.garment?.id || "", poseId: selection.pose?.id || "", parameters, ...faceOptions };
  const basis = hqBasisForPose(status, selection.pose?.id);
  const operation = readHQOperations().find(r => r.fingerprint === hqFingerprint(body, basis));
  const activeProfile = profileOnly && profileId === selectedProfile?.id ? selectedProfile : null;
  const validProfile = !profileOnly || !!activeProfile && !profileLoading && !profileError && activeProfile.state === "ready" && (activeProfile.referenceKind ?? "faceid") === "faceid" && compatibleProfile(activeProfile);
  const validFace = Number.isFinite(faceOptions.faceRestoreStrength) && faceOptions.faceRestoreStrength >= 0 && faceOptions.faceRestoreStrength <= 1 && (!faceOptions.facePolish || identityStatus?.facePolish?.ready === true && !identityError);
  const presetMismatch = Boolean(status?.pipeline && !isHQBasis(status.pipeline));
  const routeReady = status?.posePipelineReady?.[basis] ?? status?.modelReady;
  const ready = reconciled && !presetMismatch && validProfile && validFace && status?.configured === true && (profileOnly || status.authorized === true) && routeReady === true && !connectionError;
  const allSelected = !!(selection.garment && selection.pose && (profileOnly ? profileId : selection.person));
  const retryJobs = job?.id === activeId ? [job, ...jobs.filter(item => item.id !== job.id)] : jobs;
  const retryJob = reconciled && !loading && !detailLoading && !connectionError && !detailError && jobsRevision === refresh && detailRevision === refresh
    && job?.id === activeId && job.id === operation?.jobId ? retryableHQJob(operation, retryJobs) : undefined;
  const currentStatus = connectionError ? null : status;
  let noticeText = "";
  if (notice?.jobId === activeId) {
    if (notice.kind === "copied") noticeText = "完整任务编号已复制。";
    else if (job?.id === activeId && !hqActive(job)) noticeText = `任务${hqStateLabels[job.state]}。`;
    else noticeText = notice.kind === "cancel" ? "已请求取消，等待本机任务确认。" : "任务已提交至本机队列。实际成片完成并校验后，可在下方查看和下载。";
  }

  useEffect(() => {
    if (activeSelection.current.id !== activeId) activeSelection.current = { id: activeId };
    setNotice(current => current?.jobId === activeId ? current : null); setActionError("");
  }, [activeId]);

  useEffect(() => { writeHQDraft({ selection, parameters, personSource, profileId: profileId || null, ...faceOptions, activeJobId: activeId, autoRepairEnabled }); }, [selection, parameters, personSource, profileId, faceOptions, activeId, autoRepairEnabled]);

  useEffect(() => {
    const controller = new AbortController(); let alive = true; setIdentityError("");
    Promise.all([identityApi.profiles(controller.signal), identityApi.status(controller.signal)]).then(([items, capability]) => {
      if (!alive) return;
      setProfiles(items.filter(item => (item.referenceKind ?? "faceid") === "faceid" && item.state !== "archived")); setIdentityStatus(capability);
    }).catch(e => { if (alive) { setIdentityError(describe(e)); setIdentityStatus(null); } });
    return () => { alive = false; controller.abort(); };
  }, [catalogRefresh]);

  useEffect(() => {
    setSelectedProfile(null); setProfileError("");
    if (!profileId) { setProfileLoading(false); return; }
    const controller = new AbortController(); let alive = true; setProfileLoading(true);
    identityApi.profile(profileId, controller.signal).then(value => {
      if (!alive) return;
      if (value.id !== profileId || (value.referenceKind ?? "faceid") !== "faceid" || value.state !== "ready") throw new Error("请选择已就绪的 FaceID 人物档案");
      setSelectedProfile(value);
    }).catch(e => { if (alive) setProfileError(describe(e)); }).finally(() => { if (alive) setProfileLoading(false); });
    return () => { alive = false; controller.abort(); };
  }, [profileId, catalogRefresh]);

  useEffect(() => {
    const controller = new AbortController(); let alive = true;
    setLoading(true);
    Promise.all([hqApi.status(controller.signal, personSource), hqApi.jobs(controller.signal)]).then(([nextStatus, nextJobs]) => {
      if (!alive) return;
      setStatus(nextStatus); setJobs(nextJobs);
      const successors = new Map<string, string>();
      reconcileHQOperations(nextJobs, (previousId, nextId) => successors.set(previousId, nextId));
      setReconciled(true); setJobsRevision(refresh); setConnectionError("");
      const pendingKey = pendingCreate.current?.idempotencyKey;
      const pendingJob = pendingKey ? nextJobs.find(item => item.idempotencyKey === pendingKey) : undefined;
      setReceiptVersion(n => n + 1);
      setActiveId(id => {
        const selected = pendingJob?.id || id;
        return successors.get(selected) || selected || nextJobs[0]?.id || "";
      });
    }).catch(e => { if (alive) { setReconciled(false); setConnectionError(describe(e)); } }).finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; controller.abort(); };
  }, [refresh, personSource]);

  useEffect(() => {
    if (!canReadCatalog) { setLoadedCatalog(null); setCatalogLoading(false); return; }
    const controller = new AbortController(); let alive = true;
    setCatalogLoading(true); setCatalogError(""); setLoadedCatalog(null);
    hqApi.catalog(kind, filters.q, filters.category, filters.page, controller.signal).then(value => { if (alive) setLoadedCatalog({ key: catalogKey, data: value }); })
      .catch(e => { if (alive) setCatalogError(describe(e)); }).finally(() => { if (alive) setCatalogLoading(false); });
    return () => { alive = false; controller.abort(); };
  }, [kind, filters, canReadCatalog, catalogKey]);

  useEffect(() => {
    const epoch = ++detailEpoch.current;
    if (!activeId) { setJob(null); return; }
    const controller = new AbortController(); let alive = true;
    setDetailLoading(true); setDetailError("");
    setJob(previous => previous?.id === activeId ? previous : null);
    hqApi.job(activeId, controller.signal).then(value => { if (alive && epoch === detailEpoch.current) { setJob(value); setDetailRevision(refresh); } })
      .catch(e => { if (alive && epoch === detailEpoch.current) setDetailError(describe(e)); })
      .finally(() => { if (alive && epoch === detailEpoch.current) setDetailLoading(false); });
    return () => { alive = false; controller.abort(); };
  }, [activeId, refresh]);

  useEffect(() => {
    const watching = (item: HQJob) => hqActive(item) || item.bodyRepair?.state === "queued" || item.bodyRepair?.state === "running";
    if (loading || detailLoading || (!submitting && !jobs.some(watching) && !(job && watching(job)))) return;
    const timer = window.setTimeout(() => setRefresh(n => n + 1), 4000);
    return () => window.clearTimeout(timer);
  }, [jobs, job, refresh, loading, detailLoading, submitting]);

  const identityJobId = job?.id === activeId ? job.identityJobId : null;
  const resultDeleted = !!(job?.historyDeleted || job?.resultDeleted || identityJobId && (deletedImages.has(identityJobId)
    || linkedIdentity?.id === identityJobId && (linkedIdentity.historyDeleted || linkedIdentity.resultDeleted)));
  const identityReadable = !!job?.identityResult || ["identity_queued", "preparing", "sampling", "polishing", "face_polish", "face-polish", "complete", "succeeded"].includes(job?.phase || "") || job?.state === "succeeded";
  useEffect(() => {
    setLinkedIdentityError(""); setLinkedIdentity(previous => previous?.id === identityJobId ? previous : null);
    if (!identityJobId || !identityReadable || resultDeleted) return;
    const controller = new AbortController(); let alive = true;
    identityApi.job(identityJobId, controller.signal).then(value => {
      if (!alive) return;
      if (value.id !== identityJobId) throw new Error("关联人物任务编号不匹配");
      setLinkedIdentity(value);
    }).catch(e => { if (alive) setLinkedIdentityError(describe(e)); });
    return () => { alive = false; controller.abort(); };
  }, [identityJobId, identityReadable, resultDeleted, refresh, resultRefresh]);

  const resultSha = job?.result?.sha256 || job?.output?.sha256;
  useEffect(() => {
    setResultUrl(""); setResultError("");
    if (!job || job.id !== activeId || job.state !== "succeeded" || resultDeleted) return;
    const controller = new AbortController(); let alive = true, url = "";
    hqApi.result(job, controller.signal).then(blob => {
      if (!alive) return;
      url = URL.createObjectURL(blob); setResultUrl(url);
    }).catch(e => { if (alive) setResultError(describe(e)); });
    return () => { alive = false; controller.abort(); if (url) URL.revokeObjectURL(url); };
    // Refresh explicitly retries result verification; progress-only updates do not reload pixels.
  }, [activeId, job?.id, job?.state, resultSha, resultDeleted, resultRefresh]);

  function refreshJobs(withCatalog = false) {
    setRefresh(n => n + 1); setResultRefresh(n => n + 1);
    if (withCatalog) setCatalogRefresh(n => n + 1);
  }

  function switchKind(next: HQRole) { setKind(next); setSearch(""); setFilters({ q: "", category: "", page: 0 }); }
  function switchPersonSource(next: HQPersonSource) {
    if (next === personSource) return;
    setPersonSource(next); setProfileId(""); setSelectedProfile(null); setProfileError("");
    setSelection(({ person: _person, ...outfit }) => outfit);
    setStatus(null); setCatalogError(""); setReconciled(false); setActionError("");
    if (next === "gallery") switchKind("person");
    else if (kind === "person") switchKind("garment");
  }
  function searchCatalog(event: FormEvent) { event.preventDefault(); setFilters(current => ({ ...current, q: search.trim(), page: 0 })); }
  async function generate(newAttempt = false) {
    if (submittingRef.current || !allSelected || !ready || !validHQParameters(parameters)) return;
    if (newAttempt && (!retryJob || !operation)) return;
    if (!newAttempt && operation?.jobId) { setActiveId(operation.jobId); setRefresh(n => n + 1); return; }
    submittingRef.current = true; setSubmitting(true); setActionError(""); setNotice(null);
    let dispatched = false;
    try {
      const receipt = newAttempt ? await reserveHQRetry(body, retryJobs, operation!.idempotencyKey, basis) : reserveHQOperation(body, jobs, basis);
      if (receipt.jobId) { setActiveId(receipt.jobId); setRefresh(n => n + 1); return; }
      saveHQOperation({ ...receipt, delivery: "unknown" });
      pendingCreate.current = receipt;
      dispatched = true;
      const created = await hqApi.create({ ...body, ...(autoRepairEnabled ? {} : { autoRepairEnabled: false }), idempotencyKey: receipt.idempotencyKey });
      if (created.id === receipt.retryOf || created.idempotencyKey && created.idempotencyKey !== receipt.idempotencyKey) throw new Error("服务回执与本次请求不匹配");
      saveHQOperation({ ...receipt, jobId: created.id, delivery: "submitted" });
      setActiveId(created.id);
      // Polling or cancellation may already have a newer state than the POST receipt.
      setJob(previous => previous?.id === created.id ? previous : created);
      setJobs(previous => previous.some(item => item.id === created.id) ? previous : [created, ...previous]);
      setNotice(current => current?.jobId === created.id && current.kind === "cancel" ? current : { jobId: created.id, kind: "submitted" });
      setRefresh(n => n + 1);
    } catch (e) {
      setActionError(dispatched ? `提交未确认：${describe(e)}。请先刷新任务；再次点击只重发同一请求编号。` : `尚未提交：${describe(e)}`);
    } finally { submittingRef.current = false; pendingCreate.current = null; setSubmitting(false); setReceiptVersion(n => n + 1); }
  }
  async function cancel() {
    if (!job || cancellingRef.current.has(job.id) || !hqActive(job) || job.cancellationRequested) return;
    const id = job.id, selection = activeSelection.current; cancellingRef.current.add(id); setCancelling(new Set(cancellingRef.current)); setActionError(""); detailEpoch.current++;
    try {
      const updated = await hqApi.cancel(id); setJob(current => current?.id === id ? updated : current); setJobs(current => current.map(item => item.id === id ? updated : item));
      if (activeSelection.current === selection && selection.id === id) setNotice({ jobId: id, kind: "cancel" });
    }
    catch (e) { if (activeSelection.current === selection) setActionError("取消未确认：" + describe(e) + "。请刷新查看实际状态。"); }
    finally { cancellingRef.current.delete(id); setCancelling(new Set(cancellingRef.current)); setRefresh(n => n + 1); }
  }
  async function copyJobId(id: string) {
    const selection = activeSelection.current;
    try { await navigator.clipboard.writeText(id); if (activeSelection.current === selection && selection.id === id) setNotice({ jobId: id, kind: "copied" }); }
    catch { if (activeSelection.current === selection) setActionError("复制不可用，可从任务标题的悬停提示查看完整编号。"); }
  }

  return <div className="hq-page">
    <section className="surface-card hq-status" aria-label="本地 HQ 状态">
      <div className="card-head"><h2>本机三图试衣</h2><button className="secondary-button" disabled={loading} onClick={() => refreshJobs(true)}>刷新图库与任务</button></div>
      <p>使用 Realistic Vision V5.1 和 FaceID 固定人物，结合服装原图生成一张全身成片。可选修脸和独立精修。</p>
      {currentStatus?.pipeline === hqExecutionBasis && <p>选材时预览白模，Dream 本机生成时按姿势和视角读取配对深度图。当前已配对 {currentStatus.pairedDepthPoseIds?.length ?? 0} 个姿势。</p>}
      {presetMismatch && <p className="hq-error">本地服务使用旧管线，请启用配对深度版本后刷新页面。</p>}
      <p className="hq-hint">服装为图像参考生成，版型、配饰和细节可能有偏差，请对照原图验收。</p>
      <ol className="hq-workflow" aria-label="人物试衣流程"><li>固定人物与构图</li><li>底图</li><li>可选换脸</li><li>独立精修</li></ol>
      <div className="hq-status-line" role="status">
        <span>{connectionError ? "本机服务离线" : currentStatus ? currentStatus.configured ? "已配置" : "尚未配置" : "正在连接本地服务…"}</span>
        <span>{profileOnly ? "使用本机人物档案" : currentStatus ? currentStatus.authorized ? "图库已授权" : "图库未授权" : "授权状态未知"}</span>
        <span>{currentStatus ? currentStatus.modelReady ? "模型文件齐备" : "模型未就绪" : "模型状态未知"}</span>
        {currentStatus?.pipeline && <span>管线：{currentStatus.pipeline}</span>}
      </div>
      {connectionError && status && <p className="hq-hint">上次状态已过期，授权和模型状态等待重新读取。</p>}
      {currentStatus && !profileOnly && (!currentStatus.configured || !currentStatus.authorized) && <p className="hq-hint">请在本机完成 HQ 图库授权配置，然后刷新。此页无需输入图库密钥。</p>}
      {currentStatus && !currentStatus.modelReady && <p className="hq-hint">本地三图管线尚未就绪，暂不能提交生成；可查看已有任务。</p>}
      {hqError(currentStatus?.error) && <p role="alert" className="hq-error">{hqError(currentStatus?.error)}</p>}
      {connectionError && <p role="alert" className="hq-error">本地服务不可用：{connectionError}</p>}
    </section>

    <div className="hq-compose">
      <section className="surface-card hq-catalog" aria-label="HQ 原图图库">
        <h2>1 · 选择人物、服装和姿势</h2>
        <fieldset className="hq-person-source"><legend>人物来源</legend>
          <label><input type="radio" name="hq-person-source" checked={!profileOnly} onChange={() => switchPersonSource("gallery")} />图库照片</label>
          <label><input type="radio" name="hq-person-source" checked={profileOnly} onChange={() => switchPersonSource("profile")} />只选本机档案</label>
        </fieldset>
        {profileOnly && <div className="hq-profile">
          <label>本机人物档案<select value={profileId} onChange={e => setProfileId(e.target.value)}>
            <option value="">请选择人物档案</option>
            {profiles.map(profile => <option key={profile.id} value={profile.id} disabled={profile.state !== "ready" || !compatibleProfile(profile)}>{profile.name}{profile.state !== "ready" ? " · 尚未就绪" : !compatibleProfile(profile) ? " · 底模不兼容" : ""}</option>)}
            {profileId && !profiles.some(profile => profile.id === profileId) && <option value={profileId}>所选档案暂不可用</option>}
          </select></label>
          <p className="hq-hint">使用建档时选定的人脸和参考图。服装和姿势仍从下方图库选择。</p>
          {profileLoading && <p role="status">正在核对人物档案…</p>}
          {profileError && <p className="hq-error" role="alert">{profileError}</p>}
        </div>}
        <div className="hq-tabs" role="tablist" aria-label="素材角色">{hqRoles.map(role => <button key={role} role="tab" disabled={profileOnly && role === "person"} aria-selected={kind === role} onClick={() => switchKind(role)}>{hqRoleLabels[role]}</button>)}</div>
        <form className="hq-filters" onSubmit={searchCatalog}>
          <input type="search" aria-label="搜索 HQ 素材" placeholder="名称或编号" value={search} onChange={e => setSearch(e.target.value)} />
          <select aria-label="HQ 素材分类" value={filters.category} onChange={e => setFilters(current => ({ ...current, category: e.target.value, q: search.trim(), page: 0 }))}>
            <option value="">全部分类</option>{[...new Set([...(catalog?.categories || []), ...(filters.category ? [filters.category] : [])])].map(category => <option key={category} value={category}>{category === "パーティ" ? "派对 / 礼服" : category}</option>)}
          </select><button className="secondary-button" type="submit">搜索</button>
        </form>
        {catalogError && <p role="alert" className="hq-error">图库读取失败：{catalogError}</p>}
        <div className="hq-catalog-grid" aria-busy={catalogLoading}>
          {catalog?.items.map(item => <button type="button" key={item.id} className="hq-asset" aria-label={`选择${hqRoleLabels[kind]} ${assetName(item)}`} aria-pressed={selection[kind]?.id === item.id} onClick={() => setSelection(previous => ({ ...previous, [kind]: item }))}>
            <HQImage src={hqApi.assetUrl(kind, item.id, true)} alt={assetName(item)} /><span>{assetName(item)}</span><small>{item.id}</small>
          </button>)}
        </div>
        {catalogLoading ? <p role="status">正在读取图库…</p> : catalog?.items.length === 0 ? <p>没有匹配的素材，请调整搜索或分类。</p> : null}
        <div className="hq-pagination"><span>{catalog ? `${catalog.total} 项 · 第 ${filters.page + 1} 页` : "原图从 HQ 图库读取"}</span>
          <button className="secondary-button" disabled={catalogLoading || filters.page === 0} onClick={() => setFilters(current => ({ ...current, page: current.page - 1 }))}>上一页</button>
          <button className="secondary-button" disabled={catalogLoading || !catalog?.hasMore} onClick={() => setFilters(current => ({ ...current, page: current.page + 1 }))}>下一页</button>
        </div>
      </section>

      <section className="surface-card hq-selection" aria-label="已选三图与生成参数">
        <h2>2 · 确认并生成</h2>
        {currentStatus?.pipeline === hqExecutionBasis && <button type="button" className="secondary-button" onClick={() => {
          setParameters({ ...defaultHQParameters }); setFaceOptions({ ...defaultHQIdentity });
        }}>套用 A/B/C 定稿参数</button>}
        {selection.pose && currentStatus && <p className="hq-hint">所选姿势使用{basis === hqExecutionBasis ? "配对深度图" : "OpenPose 骨架"}。</p>}
        {selection.pose && currentStatus?.posePipelineReady?.[basis] === false && <p role="alert" className="hq-error">所选姿势需要的本机模型尚未就绪。</p>}
        {identityError && <p className="hq-error" role="alert">人物能力读取失败：{identityError}</p>}
        <div className="hq-selected-grid">{hqRoles.map(role => {
          const local = role === "person" && profileOnly, item = selection[role];
          const url = local ? activeProfile && `/api/identity/references/${encodeURIComponent(activeProfile.referenceId)}/image` : item && hqApi.assetUrl(role, item.id);
          const name = local ? activeProfile && `${activeProfile.name} · 人脸 ${activeProfile.faceIndex + 1}` : item && assetName(item);
          return <figure key={role}><figcaption>{local ? "人物 · 本机档案" : hqRoleLabels[role]}</figcaption>
            {url ? <><HQImage src={url} alt={`已选${hqRoleLabels[role]}原图`} /><p>{name}</p><a href={url} target="_blank" rel="noreferrer">打开{hqRoleLabels[role]}原图</a></> : <p className="hq-empty">{local ? "请选择本机档案" : "尚未选择"}</p>}
          </figure>;
        })}</div>
        <label className="hq-resolution">尺寸预设<select
          value={hqResolutionPresets.some(preset => preset.width === parameters.width && preset.height === parameters.height) ? `${parameters.width}x${parameters.height}` : "custom"}
          onChange={event => {
            const preset = hqResolutionPresets.find(item => `${item.width}x${item.height}` === event.target.value);
            if (preset) setParameters(previous => ({ ...previous, width: preset.width, height: preset.height }));
          }}>
          <option value="custom">自定义尺寸</option>
          {hqResolutionPresets.map(preset => <option key={preset.label} value={`${preset.width}x${preset.height}`}>{preset.label}</option>)}
        </select></label>
        <p className="hq-hint">定稿版使用 768×1152，标准 512×768 适合快速预览。高清生成更慢，显存占用更高。可单独切换尺寸，也可恢复整套定稿参数。</p>
        <div className="hq-parameters">{([
          ["seed", "种子", 0, 2147483647, 1], ["width", "宽度", 256, 1152, 64], ["height", "高度", 256, 1152, 64], ["steps", "步数", 1, 50, 1],
        ] as const).map(([key, label, min, max, step]) => <label key={key}>{label}<input type="number" min={min} max={max} step={step} value={parameters[key]} onChange={e => setParameters(previous => ({ ...previous, [key]: Number(e.target.value) }))} /></label>)}</div>
        {!validHQParameters(parameters) && <p className="hq-error">种子需为 0–2147483647 的整数；宽高需为 256–1152 间 64 的倍数，总像素不超过 884736；步数为 1–50。</p>}
        <label className="hq-body-option"><input type="checkbox" disabled={basis !== hqExecutionBasis} checked={autoRepairEnabled && basis === hqExecutionBasis} onChange={e=>setAutoRepairEnabled(e.target.checked)} /> 成片后自动识别修图</label>
        <p className="hq-hint">{basis === hqExecutionBasis ? "检查配对深度图在膝部和衣料留下的伪影。仅保存通过检查的局部修整，原图随时可看。" : "此姿势使用骨架控制，没有配对深度图，不执行这项修整。"}</p>
        <FacePolishControls value={faceOptions} capability={identityStatus?.facePolish} defaultStrength={defaultHQIdentity.faceRestoreStrength} onChange={value => setFaceOptions({ facePolish: value.facePolish, faceRestoreStrength: value.faceRestoreStrength })} />
        <p className="hq-hint">同一组三图、人物档案和处理参数会复用请求编号。更换素材或种子可创建新任务。</p>
        <button className="primary-button hq-generate" disabled={submitting || !ready || !allSelected || !validHQParameters(parameters)} onClick={() => void generate()}>
          {submitting ? "正在提交…" : operation?.jobId ? "查看本组已有任务" : operation?.delivery === "unknown" ? "重发同一请求" : "本机生成"}
        </button>
        {retryJob && <div className="hq-result-actions"><button type="button" className="secondary-button"
          disabled={submitting || !ready || !allSelected || !validHQParameters(parameters)} onClick={() => void generate(true)}>按相同设置新建重试</button>
          <p className="hq-hint">服务已确认本组任务{hqStateLabels[retryJob.state]}。点击会以当前三图、人物选项和参数新建一次尝试，旧任务保留。</p>
        </div>}
        {operation?.delivery === "unknown" && !operation.jobId && <p className="hq-hint">上次提交尚未确认。刷新只查询已有任务，不会自动重复生成。</p>}
        {noticeText && <p role="status" className="hq-hint">{noticeText}</p>}{actionError && <p role="alert" className="hq-error">{actionError}</p>}
      </section>
    </div>

    <section className="surface-card hq-jobs" aria-label="本机试衣任务">
      <div className="card-head"><h2>3 · 本机任务与成片</h2><button className="secondary-button" disabled={loading} onClick={() => refreshJobs()}>刷新任务</button></div>
      <div className="hq-jobs-layout"><nav aria-label="试衣任务列表">{jobs.length ? jobs.map(item => <button key={item.id} className="hq-job-button" aria-pressed={activeId === item.id} onClick={() => setActiveId(item.id)}>
        <strong>{hqStateLabels[item.state]}</strong><span title={item.id}>{shortId(item.id)}</span><small>{item.createdAt || phaseLabels[item.phase || ""] || "本地任务"}</small>
      </button>) : <p>暂无本机试衣任务。</p>}</nav>
      <div className="hq-job-detail" aria-busy={detailLoading}>
        {detailError && <p role="alert" className="hq-error">任务读取失败：{detailError}</p>}
        {job && job.id === activeId ? <>
          <div className="card-head"><h3 title={job.id}>任务 {shortId(job.id)}</h3><button className="secondary-button" onClick={() => copyJobId(job.id)}>复制完整任务编号</button><button className="danger-button" disabled={cancelling.has(job.id) || !hqActive(job) || !!job.cancellationRequested} onClick={cancel}>取消任务</button></div>
          <p role="status">{hqStateLabels[job.state]}{job.phase && phaseLabels[job.phase] ? ` · ${phaseLabels[job.phase]}` : ""}{job.cancellationRequested && job.state !== "cancelled" ? " · 已请求取消，等待确认" : ""}</p>
          {job.pipeline !== hqExecutionBasis && !job.identityJobId && <p className="hq-hint">旧独立管线试验 · 尚未验证成熟人物流程</p>}
          {!resultDeleted && job.identityJobId && linkedIdentity?.id === job.identityJobId && <p className="hq-hint">人物处理：{/[\u3400-\u9fff]/.test(linkedIdentity.message) ? linkedIdentity.message : identityStateLabels[linkedIdentity.state]}</p>}
          {linkedIdentityError && <p className="hq-error" role="alert">人物结果读取失败：{linkedIdentityError}</p>}
          {typeof job.progress === "number" && Number.isFinite(job.progress) && <progress aria-label="本机任务进度" max={100} value={Math.min(100, Math.max(0, job.progress))} />}
          {job.state === "queued" && <p className="hq-hint">等待本机生成资源。其他 Dream 任务占用 GPU 时，本任务保持排队。</p>}
          {hqError(job.error) && <p role="alert" className="hq-error">{hqError(job.error)}</p>}
          {typeof job.error === "object" && job.error?.code === "HQ_PERSON_MISMATCH" && <p className="hq-hint">请在人物来源中重新选择图库照片或本机档案，再提交。</p>}
          {job.personSource && <p className="hq-hint">任务人物来源：{job.personSource === "profile" ? "本机档案" : "图库照片"}</p>}
          <div className="hq-input-grid">{hqRoles.map(role => {
            const input = job.inputs.find(item => item.role === role), width = input?.width ?? input?.dimensions?.width, height = input?.height ?? input?.dimensions?.height;
            return <figure key={role}><figcaption>{hqRoleLabels[role]}输入</figcaption>{input ? <>
              <HQImage src={hqApi.inputUrl(job.id, role)} alt={`任务${hqRoleLabels[role]}原图`} />
              <a href={hqApi.inputUrl(job.id, role)} target="_blank" rel="noreferrer">打开{hqRoleLabels[role]}输入原图</a>
              <p>{input.label || input.id}</p>{width && height ? <p>{width} × {height}</p> : <p>尺寸待记录</p>}
              <small>SHA-256：{input.sha256 || "尚未记录"}</small>
            </> : <p className="hq-empty">原图尚未准备完成</p>}</figure>;
          })}</div>
          {job.parameters && <p className="hq-hint">种子 {job.parameters.seed} · {job.parameters.width} × {job.parameters.height} · {job.parameters.steps} 步</p>}
          {resultDeleted && <p role="status" className="hq-hint">人物结果已从历史删除，任务参数与输入记录保留。</p>}
          {job.state === "succeeded" && !resultDeleted && <div className="hq-result">
            {job.pipeline === hqExecutionBasis && <HQBodyRepair key={job.id} job={job} original={resultUrl} refresh={()=>setRefresh(n=>n+1)} />}
            <h3>实际成片</h3>
            {job.identityJobId && <HQIdentityResult key={job.identityJobId} identity={linkedIdentity?.id === job.identityJobId ? linkedIdentity : null} unavailable={!!linkedIdentityError} refinementsAvailable={job.refinementsAvailable !== false} />}
            {resultUrl ? <>{!job.identityJobId && <ResultPreview key={resultUrl} imageUrl={resultUrl} label="HQ 本机试衣成片" />}<a className="secondary-button" href={resultUrl} target="_blank" rel="noreferrer">打开成片原文件 / 放大查看</a><a className="primary-button" href={resultUrl} download={`${job.id}.png`}>下载成片原图</a><p className="hq-hint">本次任务成片 SHA-256 已校验。精修版本使用各自的下载入口。</p><small>任务成片 SHA-256：{resultSha}</small></> : resultError ? <p className="hq-error" role="alert">{resultError}</p> : <p role="status">正在读取并校验成片…</p>}
          </div>}
          <details className="hq-audit"><summary>输入绑定与本地审计</summary><pre>{job.localAudit || job.audit ? JSON.stringify(job.localAudit || job.audit, null, 2) : "尚无审计记录。任务提交或模型就绪不代表图片已生成，也不代表三图绑定已通过验证。"}</pre></details>
        </> : <p>{detailLoading ? "正在读取任务…" : "选择一个任务查看输入、进度和成片。"}</p>}
      </div></div>
    </section>
  </div>;
}

function HQIdentityResult({ identity, unavailable, refinementsAvailable }: { identity: IdentityJob | null; unavailable: boolean; refinementsAvailable: boolean }) {
  const [refining, setRefining] = useState<"default" | "upscale" | null>(null);
  const [refinements, setRefinements] = useState<RefinementSnapshot | null>(null);
  const sourceId = !unavailable && identity?.state === "complete" && identity.result ? identity.id : null;
  useEffect(() => {
    if (!sourceId || !refinementsAvailable || refining) return;
    const request = new AbortController();
    setRefinements(null);
    void refinementApi.list(sourceId, request.signal).then(data => {
      if (!request.signal.aborted) setRefinements(data);
    }).catch(() => { if (!request.signal.aborted) setRefinements(null); });
    return () => request.abort();
  }, [sourceId, refinementsAvailable, refining]);
  return <div className="hq-identity-result">
    {!unavailable && identity?.state === "complete" && identity.result ? <>
      <JobResultPreview job={identity} />
      {refinementsAvailable && <div className="hq-result-actions">
        <button className="secondary-button" disabled={!!refining} onClick={() => setRefining("default")}>独立精修与版本对比</button>
        {refinements?.sourceJobId === identity.id && refinements.modes?.includes("upscale") && <button className="primary-button" disabled={!!refining} onClick={() => setRefining("upscale")}>2倍清晰增强</button>}
      </div>}
      {refining && refinementsAvailable && <RefinementWorkspace sourceJobId={identity.id} initialMode={refining === "upscale" ? "upscale" : undefined}
        onSnapshot={setRefinements} onClose={() => setRefining(null)} />}
    </> : !unavailable && <p role="status">正在核对人物底图与可选换脸结果…</p>}
  </div>;
}

function HQImage({ src, alt }: { src: string; alt: string }) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [src]);
  return failed ? <span className="hq-empty" role="img" aria-label={`${alt}不可用`}>图像暂不可用</span> : <img src={src} alt={alt} loading="lazy" onError={() => setFailed(true)} />;
}
