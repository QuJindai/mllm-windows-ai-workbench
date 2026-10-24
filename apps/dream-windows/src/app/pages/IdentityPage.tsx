import { useCallback, useEffect, useRef, useState } from "react";
import type { FormEvent, SetStateAction } from "react";
import { IDENTITY_MODEL_ID, ILLUSTRIOUS_IDENTITY_MODEL_ID, identityFacePolishOptions, identityModelDefaults, identityReferenceKind, identityStateLabels, isIdentityModelId, normalizeIdentityOptions, validAnimeStrength, validFaceRestoreStrength, validVisualAnchorStrength, validVisualPolishMode, validVisualPolishPasses, visualPolishDefaults } from "../../domain/identity";
import type { IdentityFacePolishOptions, IdentityRequest } from "../../domain/identity";
import { BatchControls, defaultBatchSettings, validBatchSettings } from "../components/identity/BatchControls";
import type { BatchSettings } from "../components/identity/BatchControls";
import { FacePicker } from "../components/identity/FacePicker";
import { FacePolishControls } from "../components/identity/FacePolishControls";
import { VisualPolishControls } from "../components/identity/VisualPolishControls";
import { AnimeProfileLibrary } from "../components/identity/AnimeProfileLibrary";
import { useAnimeProfiles } from "../components/identity/useAnimeProfiles";
import { IdentityResults } from "../components/identity/IdentityResults";
import { BatchRetryActions } from "../components/BatchRetryActions";
import { ProfileLibrary } from "../components/identity/ProfileLibrary";
import { useIdentityWorkspace } from "../components/identity/useIdentityWorkspace";
import type { IdentityReplay, RestoredIdentity } from "../components/identity/useIdentityWorkspace";
import "./identity-page.css";

export type { IdentityReplay } from "../components/identity/useIdentityWorkspace";
const DRAFT_KEY = "dream.identity.text-draft.v1";
function researchFitsBudget(value: Omit<IdentityRequest, "referenceId" | "faceIndex" | "seed">, steps: number) {
  if (value.traceLevel !== "h7") return true;
  const extended = value.researchCoverage === "extended";
  const grids = Array.from({length:4}, (_,i) => Math.ceil(value.width/8/2**i)*Math.ceil(value.height/8/2**i));
  const area = extended ? grids.slice(0,3).reduce((sum,n) => sum+5*n,0)+grids[3] : 2*grids[0]+grids[3];
  const tokens = Math.min(extended ? 75 : 32, Math.max(1, new TextEncoder().encode(value.prompt).length));
  const samples = extended ? steps : Math.min(steps,5);
  const maps = samples*(extended ? 16 : 3)*(tokens+9);
  return samples*area*(tokens+9)*26 + maps*1400 + steps*grids[0]*8 + 8*1024*1024 <= 512*1024*1024;
}
type FormValues = Omit<IdentityRequest, "referenceId" | "faceIndex" | "seed"> & { seed: string };
type TextDraft = { prompt: string; negativePrompt: string; modelId?: string; polishContext?: string; parameters?: Partial<FormValues>; batchSettings?: BatchSettings } & IdentityFacePolishOptions;
// Only allow form fields into browser storage, never reference pixels or features.
function readParameters(value: unknown): Partial<FormValues> | undefined {
  if (!value || typeof value !== "object" || Array.isArray(value)) return undefined;
  const fields = value as Record<string, unknown>, result: Partial<FormValues> = {};
  for (const key of ["width", "height", "steps", "cfg", "identityStrength", "structureStrength", "faceLoraStrength", "loraStrength", "referenceStart", "referenceEnd"] as const) {
    if (typeof fields[key] === "number") result[key] = fields[key];
    // JSON represents a cleared numeric input (NaN) as null; preserve its invalid state.
    else if (fields[key] === null) result[key] = NaN;
  }
  for (const key of ["seed", "loraId"] as const) if (typeof fields[key] === "string") result[key] = fields[key];
  if (["off", "basic", "h6", "h7"].includes(String(fields.traceLevel))) result.traceLevel = fields.traceLevel as IdentityRequest["traceLevel"];
  if (["representative", "extended"].includes(String(fields.researchCoverage))) result.researchCoverage = fields.researchCoverage as IdentityRequest["researchCoverage"];
  return result;
}
function readBatchSettings(value: unknown): BatchSettings | undefined {
  if (!value || typeof value !== "object" || Array.isArray(value)) return undefined;
  const fields = value as Record<string, unknown>;
  if (!(fields.count === null || typeof fields.count === "number") || typeof fields.previewEvery !== "number" || ![0, 5, 10].includes(fields.previewEvery)) return undefined;
  return { count: fields.count === null ? NaN : fields.count as number, previewEvery: fields.previewEvery as BatchSettings["previewEvery"],
    ...(Array.isArray(fields.stepValues) && fields.stepValues.every(n => typeof n === "number") ? { stepValues: fields.stepValues } : {}) };
}
function readDraft(): TextDraft | null {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(DRAFT_KEY) ?? "null");
    if (value && typeof value === "object" && "prompt" in value && typeof value.prompt === "string" && "negativePrompt" in value && typeof value.negativePrompt === "string") {
      const fields = value as Record<string, unknown>;
      return normalizeIdentityOptions({ prompt: value.prompt, negativePrompt: value.negativePrompt, ...identityFacePolishOptions(fields),
        ...(typeof fields.modelId === "string" && isIdentityModelId(fields.modelId) ? { modelId: fields.modelId } : {}),
        ...(typeof fields.polishContext === "string" ? { polishContext: fields.polishContext } : {}),
        parameters: readParameters(fields.parameters), batchSettings: readBatchSettings(fields.batchSettings) });
    }
  } catch { /* Disabled or corrupt storage must not prevent use. */ }
  return null;
}

export function IdentityPage({ replay }: { replay?: IdentityReplay | null }) {
  const [savedDraft] = useState(readDraft);
  const [draftDirty, setDraftDirty] = useState(!!savedDraft?.parameters);
  const [form, setForm] = useState<FormValues>(() => normalizeIdentityOptions({ ...identityModelDefaults(savedDraft?.modelId ?? (savedDraft?.animeProfileId ? ILLUSTRIOUS_IDENTITY_MODEL_ID : IDENTITY_MODEL_ID)),
    ...(savedDraft ? { prompt: savedDraft.prompt, negativePrompt: savedDraft.negativePrompt, ...identityFacePolishOptions(savedDraft),
      ...(savedDraft.animeProfileId ? {modelId:ILLUSTRIOUS_IDENTITY_MODEL_ID} : {}) } : {}), seed: "random", ...savedDraft?.parameters }));
  const [referenceId, setReferenceId] = useState("");
  const [faceIndex, setFaceIndex] = useState<number | null>(null);
  const [settings, setSettings] = useState<BatchSettings>(() => savedDraft?.batchSettings ?? defaultBatchSettings);
  const [newPersonRevision, setNewPersonRevision] = useState(0);
  const uploadInput = useRef<HTMLInputElement>(null);
  useEffect(() => { if (newPersonRevision) uploadInput.current?.focus(); }, [newPersonRevision]);
  const restore = useCallback(({ request, batch, allowDraft, polishDraftContext }: RestoredIdentity) => {
    const { referenceId: id, faceIndex: face, ...parameters } = request;
    setReferenceId(id); setFaceIndex(face);
    const restorePolishDraft = savedDraft && polishDraftContext && polishDraftContext === savedDraft.polishContext;
    const restoreFullDraft = !!(allowDraft && restorePolishDraft && savedDraft?.parameters);
    setDraftDirty(restoreFullDraft);
    const animeDraft = identityReferenceKind(parameters.modelId) !== "visual" && restorePolishDraft && savedDraft?.animeProfileId;
    const restoredModel = restorePolishDraft && savedDraft.modelId ? savedDraft.modelId
      : animeDraft ? ILLUSTRIOUS_IDENTITY_MODEL_ID : parameters.modelId;
    const changedModel = (restoredModel ?? IDENTITY_MODEL_ID) !== (parameters.modelId ?? IDENTITY_MODEL_ID);
    setForm(normalizeIdentityOptions({ ...parameters,
      ...(changedModel ? { ...identityModelDefaults(restoredModel), prompt: parameters.prompt, negativePrompt: parameters.negativePrompt } : {}),
      ...identityFacePolishOptions(restorePolishDraft ? savedDraft : parameters),
      ...(restorePolishDraft && !savedDraft.animeProfileId && identityReferenceKind(restoredModel) !== "visual" ? {animeProfileId:undefined,animeDenoiseStrength:undefined} : {}),
      ...(allowDraft && savedDraft && (restoreFullDraft || !polishDraftContext?.startsWith("profile:")) ? { prompt: savedDraft.prompt, negativePrompt: savedDraft.negativePrompt } : {}),
      modelId: restoredModel,
      seed: String(parameters.seed), loraId: changedModel ? "" : parameters.loraId ?? "", loraStrength: parameters.loraStrength ?? 0.6,
      ...(restoreFullDraft ? savedDraft.parameters : {}) }));
    setSettings(restoreFullDraft && savedDraft.batchSettings ? savedDraft.batchSettings : batch ? { count: batch.count, previewEvery: batch.previewEvery, ...(batch.stepValues?.length ? { stepValues: batch.stepValues } : {}) } : defaultBatchSettings);
  }, [savedDraft]);
  const workspace = useIdentityWorkspace(replay, restore);
  const { status, references, selectedProfile, profileId, locked, pending, initializing, persist } = workspace;
  const models = status?.models ?? (status ? [{ id: IDENTITY_MODEL_ID, name: status.modelName, architecture: "SD1.5", ready: status.ready, message: status.message, loras: status.loras }] : []);
  const modelId = form.modelId ?? IDENTITY_MODEL_ID;
  const referenceKind = identityReferenceKind(modelId);
  const isVisual = referenceKind === "visual";
  const selectedModel = models.find(model => model.id === modelId);
  const isXL = modelId === ILLUSTRIOUS_IDENTITY_MODEL_ID;
  const anime = useAnimeProfiles(isXL || !!form.animeProfileId);
  const matchingAnime = anime.profiles.filter(p=>p.referenceId===referenceId && p.faceIndex===faceIndex);
  const loras = selectedModel?.loras ?? [];
  const polishContext = workspace.draftContext;
  useEffect(() => {
    if (initializing || workspace.opening || polishContext === null) return;
    persist(DRAFT_KEY, JSON.stringify({ modelId, prompt: form.prompt, negativePrompt: form.negativePrompt, ...identityFacePolishOptions(form), polishContext,
      ...(draftDirty ? { parameters: readParameters({ ...form, traceLevel: form.traceLevel ?? "off", researchCoverage: form.researchCoverage ?? "representative" }), batchSettings: settings } : {}) }));
  }, [modelId, form, settings, draftDirty, polishContext, initializing, workspace.opening, persist]);
  function editForm(value: SetStateAction<FormValues>) { setDraftDirty(true); setForm(value); }
  function editSettings(value: BatchSettings) { setDraftDirty(true); setSettings(value); }

  const reference = references.find((item) => item.id === referenceId);
  const compatibleReference = isVisual || reference?.referenceKind !== "visual";
  const validFace = compatibleReference && !!reference?.faces.some((face) => face.index === faceIndex);
  const validSeed = form.seed === "random" || /^\d+$/.test(form.seed) && Number.isSafeInteger(Number(form.seed)) && Number(form.seed) <= 2147483647;
  const validStrength = (value: number | undefined) => typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 1.5;
  const validNumbers = [form.width, form.height].every((value) => Number.isInteger(value) && value >= 256 && value <= 768 && value % 8 === 0)
    && Number.isInteger(form.steps) && form.steps >= 1 && form.steps <= 50
    && Number.isFinite(form.cfg) && form.cfg >= 1.01 && form.cfg <= 15
    && [form.identityStrength, form.structureStrength, form.faceLoraStrength].every(validStrength);
  const validLora = !form.loraId || loras.some((item) => item.id === form.loraId) && validStrength(form.loraStrength);
  const validReferenceInterval = !isVisual || Number.isFinite(form.referenceStart ?? 0) && Number.isFinite(form.referenceEnd ?? 1)
    && (form.referenceStart ?? 0) >= 0 && (form.referenceEnd ?? 1) <= 1 && (form.referenceStart ?? 0) < (form.referenceEnd ?? 1);
  const validProfile = !profileId || selectedProfile?.state === "ready" && selectedProfile.referenceId === referenceId && selectedProfile.faceIndex === faceIndex && (selectedProfile.referenceKind ?? "faceid") === referenceKind;
  const validStagedOptions = !isVisual || validVisualPolishMode(form.visualPolishMode ?? "redraw")
    && validVisualAnchorStrength(form.visualAnchorStrength ?? .95) && validVisualPolishPasses(form.visualPolishPasses ?? 1);
  const validPolish = !form.facePolish || validStagedOptions && (isVisual ? status?.visualPolish?.ready === true && !form.animeProfileId && validAnimeStrength(form.animeDenoiseStrength ?? .35)
    && (form.visualPolishMode !== "reference-anchor" || status?.visualPolish?.referenceAnchorReady !== false)
    && (form.visualPolishPrompt ?? "").length <= 2000 && (form.visualPolishNegativePrompt ?? "").length <= 2000
    : form.animeProfileId ? isXL && !anime.error && status?.animePolish?.ready === true
    && matchingAnime.some(p=>p.id===form.animeProfileId && p.state==='ready') && validAnimeStrength(form.animeDenoiseStrength ?? .35)
    : status?.facePolish?.ready === true && validFaceRestoreStrength(form.faceRestoreStrength));
  const validResearch = (!["h6", "h7"].includes(form.traceLevel ?? "off") || form.researchCoverage !== "extended"
    || Math.max(form.width, form.height) <= 512 && form.steps <= 12 && (settings.stepValues ?? []).every(step => step <= 12))
    && !((isXL || isVisual) && ["h6", "h7"].includes(form.traceLevel ?? "off") && form.researchCoverage === "extended")
    && [form.steps, ...(settings.stepValues ?? [])].every(step => researchFitsBudget(form, step));
  const canSubmit = !locked && status?.ready && selectedModel?.ready && validFace && validProfile && !!form.prompt.trim() && form.prompt.length <= 2000 && form.negativePrompt.length <= 2000 && validSeed && validNumbers && validLora && validPolish && validResearch && validReferenceInterval && validBatchSettings(settings);

  function selectReference(id: string) {
    workspace.clearProfile(); setReferenceId(id);
    const faces = references.find((item) => item.id === id)?.faces;
    setFaceIndex(faces?.length === 1 ? faces[0].index : null);
  }
  function newPerson() {
    if (locked) return;
    setDraftDirty(false);
    void workspace.selectProfile("");
    setReferenceId(""); setFaceIndex(null);
    setForm(normalizeIdentityOptions({ ...identityModelDefaults(isVisual ? modelId : IDENTITY_MODEL_ID), seed: "random" }));
    setSettings(defaultBatchSettings);
    setNewPersonRevision((revision) => revision + 1);
  }
  function selectModel(next: string) {
    if (selectedProfile && (selectedProfile.referenceKind ?? "faceid") !== identityReferenceKind(next)) workspace.clearProfile();
    if (identityReferenceKind(next) === "faceid") {
      if (reference?.referenceKind === "visual") { workspace.clearProfile(); setReferenceId(""); setFaceIndex(null); }
    }
    const defaults = identityModelDefaults(next);
    editForm(value => normalizeIdentityOptions({ ...value, modelId: next, loraId: "", researchCoverage: "representative",
      ...(identityReferenceKind(next) !== referenceKind ? { ...visualPolishDefaults, facePolish: false, animeDenoiseStrength: .35, visualPolishPrompt: "", visualPolishNegativePrompt: "" } : {}),
      ...(isVisual ? { identityStrength: defaults.identityStrength, structureStrength: defaults.structureStrength, faceLoraStrength: defaults.faceLoraStrength } : {}),
      ...(identityReferenceKind(next) === "visual" ? { identityStrength: .8, referenceStart: 0, referenceEnd: 1 } : { referenceStart: undefined, referenceEnd: undefined }),
      ...(next !== ILLUSTRIOUS_IDENTITY_MODEL_ID && value.animeProfileId ? { animeProfileId: undefined, facePolish: false } : {}),
      width: defaults.width, height: defaults.height, steps: defaults.steps, cfg: defaults.cfg }));
  }
  function submit(event: FormEvent) {
    event.preventDefault();
    if (!canSubmit || faceIndex === null) return;
    const { seed, loraId, loraStrength, ...parameters } = normalizeIdentityOptions(form);
    const request: IdentityRequest = { ...parameters, ...identityFacePolishOptions(parameters), referenceId, faceIndex, seed: seed === "random" ? "random" : Number(seed), ...(loraId ? { loraId, loraStrength } : {}) };
    void workspace.submit({ ...(profileId ? { profileId } : {}), request, ...settings }).then(success => { if (success) setDraftDirty(false); });
  }
  function numberField(label: string, key: "width" | "height" | "steps" | "cfg" | "identityStrength" | "structureStrength" | "faceLoraStrength" | "loraStrength" | "referenceStart" | "referenceEnd", step: number, min = 0, max = 1.5) {
    return <label>{label}<input type="number" min={min} max={max} step={step} value={Number.isFinite(form[key]) ? form[key] : ""} onChange={(event) => editForm((value) => ({ ...value, [key]: event.target.value === "" ? NaN : Number(event.target.value) }))} /></label>;
  }
  const resultRequest = workspace.batch?.request.request ?? workspace.job?.request;
  const resultReference = resultRequest ? references.find((item) => item.id === resultRequest.referenceId) : reference;

  return <section className="identity-workspace" aria-label="人物创作工作区">
    <div className="surface-card identity-runtime">
      <div><strong>{selectedModel?.name || status?.modelName || "人物运行环境"}</strong><p>{status?.message || (initializing ? "正在读取运行状态…" : "运行状态不可用")}</p></div>
      <button type="button" className="secondary-button" onClick={() => {void workspace.refresh();if(isXL) void anime.refresh();}} disabled={locked}>刷新运行状态</button>
    </div>
    <div className="identity-notices">
      <p className="identity-note">本地处理：参考图发送到当前本机 Dream 服务，图片与{isVisual ? "视觉参考" : "身份"}特征保存在本机；浏览器仅保存生成参数草稿（含模型、提示词、修脸和批次设置）及所选档案、最近批次编号，不保存图片或特征。</p>
      <p className="identity-note">{isVisual ? "模型许可：使用时需遵循底模、Plus Face 适配器、CLIP 与人脸检测权重各自的许可。" : "模型许可：现有 FaceID / InsightFace 权重有研究/非商业使用限制，尚未确认商业使用授权；使用时需遵循各模型许可。"}</p>
    </div>
    {workspace.loadError && <p className="identity-error" role="alert">{workspace.loadError}</p>}
    {workspace.error && <p className="identity-error" role="alert">{workspace.error}</p>}
    {workspace.storageNotice && <p role="status">{workspace.storageNotice}</p>}
    {workspace.notice && <p role="status">{workspace.notice}</p>}
    <div className="identity-columns">
      <form className="surface-card identity-controls" onSubmit={submit}>
        <label>人物底图模型<select value={modelId} disabled={locked} onChange={event => selectModel(event.target.value)}>
          {models.map(model => <option key={model.id} value={model.id}>{model.name} · {model.architecture}{model.ready ? "" : " · 不可用"}</option>)}
          {!selectedModel && <option value={modelId}>原任务底模当前不可用</option>}
        </select></label>
        {isVisual && <p className="identity-note">动漫视觉参考 · Plus Face + CLIP。上传只做人脸检测，不提取 FaceID 身份识别特征；侧脸与姿态尚不稳定，不保证人物相似度。首次使用本模式需重新计算视觉特征缓存，可能较慢。</p>}
        <ProfileLibrary key={profileId + ":" + (selectedProfile?.name ?? "")} profiles={workspace.profiles} profileId={profileId} profile={selectedProfile}
          referenceKind={referenceKind}
          disabled={locked} selectionDisabled={workspace.active || !!pending || workspace.refreshing || initializing}
          canCreate={validFace && !!status?.ready}
          onNew={newPerson}
          onSelect={(id) => { if (!id) { setReferenceId(""); setFaceIndex(null); } void workspace.selectProfile(id); }}
          onCreate={(name) => { if (faceIndex !== null) void workspace.createProfile(name, referenceId, faceIndex, referenceKind); }}
          onRename={(name) => void workspace.renameProfile(name)} onArchive={workspace.archiveProfile} />
        <fieldset disabled={locked}>
          <legend>1 · 参考照与人物</legend>
          <fieldset disabled={!!profileId} className="identity-reference-controls" aria-label="人物参考照">
            <label>上传参考照<input ref={uploadInput} type="file" accept="image/png,image/jpeg,image/webp" onChange={(event) => {
              const file = event.target.files?.[0]; event.target.value = "";
              if (file) {
                setReferenceId(""); setFaceIndex(null);
                void workspace.upload(file, (value) => { setReferenceId(value.id); setFaceIndex(value.faces.length === 1 ? value.faces[0].index : null); }, referenceKind);
              }
            }} /></label>
            <p className="identity-note">PNG / JPEG / WebP，最多 10 MiB、1600 万像素。照片仅上传到本机人物服务。</p>
            {pending === "upload" && <p role="status">正在上传并分析参考照…</p>}
            <label>选择参考照<select value={referenceId} onChange={(event) => selectReference(event.target.value)}>
              <option value="">请选择参考照</option>{references.filter(item => isVisual || item.referenceKind !== "visual").map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
            </select></label>
            {referenceId && !reference && !initializing && <p className="identity-error">任务参考照不可用，请重新上传或选择。</p>}
            {!compatibleReference && <p className="identity-error" role="alert">此图片仅支持视觉参考，不能用于 FaceID；请选择动漫视觉参考模式或重新上传真人照片。</p>}
            {reference && <FacePicker key={reference.id} reference={reference} selected={faceIndex} onSelect={setFaceIndex} />}
          </fieldset>
          <h2>2 · 场景与{isVisual ? "视觉参考" : "身份"}条件</h2>
          {!selectedModel?.ready && !initializing && (status?.models || !selectedModel) && <p className="identity-error" role="alert">{selectedModel?.message ?? "所选底模不可用，请检查模型配置"}</p>}
          {isXL && <p className="identity-note">插画底模 · SDXL 专用 FaceID；复用已有档案。6GB 显存使用分段加载，速度慢于 SD1.5。支持 H6/H7 代表采集，暂不支持扩展采集；不保证人物相似度提升。</p>}
          <label>场景提示词<textarea rows={4} maxLength={2000} value={form.prompt} onChange={(event) => editForm((value) => ({ ...value, prompt: event.target.value }))} placeholder="描述人物所在的场景、服装与光线" /></label>
          <label>反向提示词<textarea rows={2} maxLength={2000} value={form.negativePrompt} onChange={(event) => editForm((value) => ({ ...value, negativePrompt: event.target.value }))} /></label>
          <div className="identity-fields">
            {numberField(isVisual ? "视觉参考强度" : "身份强度", "identityStrength", 0.01)}
            {isVisual && <>{numberField("参考开始比例", "referenceStart", .05, 0, 1)}{numberField("参考结束比例", "referenceEnd", .05, 0, 1)}</>}
            {!isVisual && <>{numberField("结构强度", "structureStrength", 0.01)}{numberField("FaceID 配套 LoRA 强度", "faceLoraStrength", 0.01)}</>}
          </div>
          {isVisual && <p className="identity-note">参考生效区间按去噪进度计；0–1 表示全程参考。缩短区间会给提示词更多自由，不保证相似度提高。</p>}
          {!validReferenceInterval && <p className="identity-error" role="alert">参考区间须在 0–1 内，开始必须小于结束。</p>}
          {!isVisual && <><label>可选 LoRA<select value={form.loraId ?? ""} onChange={(event) => editForm((value) => ({ ...value, loraId: event.target.value }))}>
            <option value="">不使用额外 LoRA</option>{loras.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
            {form.loraId && !loras.some((item) => item.id === form.loraId) && <option value={form.loraId}>原任务 LoRA 当前不可用</option>}
          </select></label>
          {form.loraId && numberField("可选 LoRA 强度", "loraStrength", 0.01)}
          {!validLora && <p className="identity-error">请选择当前可用的 LoRA，或取消额外 LoRA。</p>}</>}
          {isVisual ? <VisualPolishControls value={form} capability={status?.visualPolish} reference={reference} faceIndex={faceIndex}
            onChange={value => editForm(current => ({ ...current, ...value }))} /> : <FacePolishControls value={form} capability={status?.facePolish} animeCapability={status?.animePolish} animeProfiles={matchingAnime}
            allowAnime={isXL} onChange={(value) => editForm((current) => ({ ...current, ...value }))} />}
          {isXL && <AnimeProfileLibrary key={selectedProfile?.id ?? 'none'} profiles={matchingAnime} profile={selectedProfile} jobs={workspace.jobs}
            pending={anime.pending} error={anime.error} onCreate={anime.create} onImport={anime.importImage} />}
          <h2>3 · 生成参数</h2>
          <div className="identity-fields">{numberField("宽度", "width", 8, 256, 768)}{numberField("高度", "height", 8, 256, 768)}{numberField("步数", "steps", 1, 1, 50)}{numberField("CFG", "cfg", 0.01, 1.01, 15)}</div>
          <label>种子<input type="text" value={form.seed} onChange={(event) => editForm((value) => ({ ...value, seed: event.target.value.trim() }))} aria-describedby="identity-seed-hint" /></label>
          <p id="identity-seed-hint" className="identity-note">输入 random 使用随机种子，或填写非负整数以复现任务。</p>
          {!validSeed && <p className="identity-error">种子必须是 random 或 0–2147483647 的整数。</p>}
          {!validNumbers && <p className="identity-error">尺寸需为 256–768 内的 8 的倍数；步数 1–50；CFG 1.01–15；强度 0–1.5。</p>}
          <BatchControls value={settings} onChange={editSettings} />
          <h2>5 · 人物显微镜（可选）</h2>
          <label>人物显微镜采集<select value={form.traceLevel ?? "off"} onChange={event => editForm(value => ({ ...value, traceLevel: event.target.value as IdentityRequest["traceLevel"] }))}>
            <option value="off">关闭 · 正常生成</option><option value="basic">基础 · 潜空间与运行记录</option><option value="h6">H6 · {isVisual ? "视觉参考条件影响" : "身份条件影响"}</option><option value="h7">H7 · 条件影响与自/文本交叉注意力</option>
          </select></label>
          {isVisual && <p className="identity-note">H6 测量关闭视觉参考后的预测差异；H7 记录自注意力与文本交叉注意力，不是图片 Token 归因或人物相似度评分。</p>}
          {form.traceLevel && form.traceLevel !== "off" && <>
            <label>研究采集范围<select value={form.researchCoverage ?? "representative"} onChange={event => editForm(value => ({ ...value, researchCoverage: event.target.value as IdentityRequest["researchCoverage"] }))}>
              <option value="representative">代表采集 · 3 层 / 最多 5 步 / 32 Token</option><option value="extended" disabled={isXL || isVisual}>扩展采集 · 全部注意力层 / 全步骤 / 有效文本 Token</option>
            </select></label>
            <p className="identity-note">采集使用真实张量，增加耗时和本机产物，不调整人物强度或修脸。注意力为条件分支的多头均值；Self 采集每层最多9个空间锚点，不是全空间矩阵。扩展研究限512×512、12步，产物上限512MiB。</p>
            {!validResearch && <p className="identity-error" role="alert">扩展研究请将宽高均设为不超过512、步数不超过12，并取消超过12步的步数对照；长提示词预估超过512MiB时请改为8步，或改用代表采集。</p>}
          </>}
        </fieldset>
        <button className="primary-button" type="submit" disabled={!canSubmit}>{pending === "submit" ? "正在提交…" : "生成人物图像"}</button>
        {workspace.active && <p className="identity-note">任务执行期间参数已冻结。切换页面不会中止任务。</p>}
      </form>
      <IdentityResults batch={workspace.batch} job={workspace.job} reference={resultReference} profile={selectedProfile}
        opening={workspace.opening} cancelling={pending === "cancel"} pending={!!pending} pollError={workspace.pollError}
        onCancel={() => void workspace.cancel()} onSavePreset={(value) => void workspace.savePreset(value)} />
    </div>
    <section className="surface-card identity-history" aria-label="人物批次历史">
      <h2>人物批次历史</h2>
      {workspace.batch && <BatchRetryActions batch={workspace.batch} disabled={locked} onRetry={workspace.retryBatch} />}
      {workspace.batches.length ? <ul>{workspace.batches.map((item) => <li key={item.id}><button type="button" className="secondary-button" disabled={!!pending} aria-pressed={item.id === workspace.batch?.id} aria-label={"打开人物批次 " + item.id} onClick={() => void workspace.openBatch(item.id)}>
        <strong>{identityStateLabels[item.state]}</strong><span>{item.request.request.prompt} · {item.completedItems} / {item.totalItems} 张</span><small>{item.id}</small>
      </button></li>)}</ul> : <p className="identity-note">暂无人物批次。</p>}
    </section>
    <section className="surface-card identity-history" aria-label="人物任务历史">
      <h2>人物任务历史</h2>
      {workspace.jobs.length ? <ul>{workspace.jobs.map((item) => <li key={item.id}><button type="button" className="secondary-button" disabled={!!pending} aria-pressed={item.id === workspace.job?.id} aria-label={"打开人物任务 " + item.id} onClick={() => void workspace.openJob(item.id)}>
        <strong>{identityStateLabels[item.state]}</strong><span>{item.request.prompt}</span><small>{item.id}</small>
      </button></li>)}</ul> : <p className="identity-note">暂无人物任务。历史任务可打开、查看结果并重新使用参数。</p>}
    </section>
  </section>;
}
